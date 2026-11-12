"""Opt-in, caller-bound gateway cost observations; never executes provider work.

Composition owns case grants and pinned tariffs. HTTP carries only an opaque grant
reference. SQLite commits admission before paid work and deduplicates observations
and canonical events together. A pending/failed observation blocks cost closure.
Exports are a dedicated cost stream to be joined with HeyAsa execution events.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

from .kpi_ledger import (
    DeploymentContext,
    IncompleteCostMeasurementError,
    KpiCostLedger,
    KpiLedgerError,
    _parse_non_negative_decimal,
    _require_id,
    _utc_now,
)

LOG = logging.getLogger(__name__)
ACTIVE_COST: ContextVar = ContextVar("subllm_business_cost", default=None)


class CostAdmissionError(RuntimeError):
    """Cost observation admission failed before the provider was called."""


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _key(*parts):
    return hashlib.sha256(_json(parts).encode()).hexdigest()


@dataclass(frozen=True)
class TokenTariff:
    """Explicit price snapshot per million actual input/output tokens."""

    input_per_million: str
    output_per_million: str
    price_ref: str
    currency: str = "PLN"
    fx_rate_to_pln: str | None = None
    fx_ref: str | None = None

    def __post_init__(self):
        _require_id(self.price_ref, "price_ref")
        for name in ("input_per_million", "output_per_million"):
            value = _parse_non_negative_decimal(getattr(self, name), name)
            object.__setattr__(self, name, str(value))
        if self.currency != "PLN" and not self.fx_ref:
            raise KpiLedgerError("foreign pricing requires explicit FX provenance")
        if self.fx_ref is not None:
            _require_id(self.fx_ref, "fx_ref")
        KpiCostLedger(DeploymentContext("check", "check", "1", "check"))._resolve_pln_amount(
            amount="1", currency=self.currency, fx_rate_to_pln=self.fx_rate_to_pln,
            pricing_source="pinned_tariff", calculation_method="token_tariff", explicit_zero=False,
        )

    def quote(self, input_tokens, output_tokens):
        amount = None
        if input_tokens is not None and output_tokens is not None:
            amount = str((Decimal(self.input_per_million) * input_tokens
                          + Decimal(self.output_per_million) * output_tokens) / 1_000_000)
        return {"amount": amount, "currency": self.currency, "fx_rate_to_pln": self.fx_rate_to_pln,
                "pricing_source": "pinned_tariff", "calculation_method": "token_tariff",
                "explicit_zero": amount is not None and Decimal(amount) == 0,
                "price_ref": self.price_ref, "fx_ref": self.fx_ref}


@dataclass
class _Capture:
    observer: GatewayCostObserver
    caller: str
    reference: str
    request_id: str
    sequence: int = 0
    failed: bool = False
    context_reset: object = None


class GatewayCostObserver:
    """Trusted composition API; callers cannot grant cases or supply prices over HTTP.

    Keep the journal and exports on a private local filesystem. A request ID may
    be admitted once only; replay uses observe(), never begin() or provider calls.
    Reopening verifies immutable deployment contexts and retains original quotes.
    """

    def __init__(self, path, contexts, tariffs=None):
        self.path = Path(path)
        self.contexts = MappingProxyType(dict(contexts))
        self.tariffs = MappingProxyType(dict(tariffs or {}))
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        os.chmod(self.path, 0o600)
        with self._db() as db:
            for sql in (
                "CREATE TABLE IF NOT EXISTS contexts(caller TEXT PRIMARY KEY, body TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS cases(caller TEXT, reference TEXT, case_id TEXT, "
                "closed INTEGER DEFAULT 0, PRIMARY KEY(caller,reference), UNIQUE(caller,case_id))",
                "CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, caller TEXT, reference TEXT, "
                "model TEXT, finished INTEGER DEFAULT 0, failed INTEGER DEFAULT 0)",
                "CREATE TABLE IF NOT EXISTS observations(id TEXT PRIMARY KEY, request_id TEXT, body TEXT NOT NULL)",
                "CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, caller TEXT, "
                "reference TEXT, body TEXT NOT NULL)",
            ):
                db.execute(sql)
            for caller, context in self.contexts.items():
                _require_id(caller, "caller")
                body = _json(asdict(context))
                prior = db.execute("SELECT body FROM contexts WHERE caller=?", (caller,)).fetchone()
                if prior and prior[0] != body:
                    raise KpiLedgerError("deployment context differs from durable journal")
                db.execute("INSERT OR IGNORE INTO contexts VALUES(?,?)", (caller, body))

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _case(self, db, caller, reference):
        _require_id(caller, "caller")
        _require_id(reference, "reference")
        row = db.execute("SELECT case_id,closed FROM cases WHERE caller=? AND reference=?",
                         (caller, reference)).fetchone()
        if caller not in self.contexts or row is None:
            raise KpiLedgerError("business case reference not granted")
        return row

    def register_case(self, caller, reference, case_id):
        _require_id(reference, "reference")
        _require_id(case_id, "case_id")
        if caller not in self.contexts:
            raise KpiLedgerError("caller has no deployment context")
        with self._db() as db:
            prior = db.execute("SELECT case_id FROM cases WHERE caller=? AND reference=?",
                               (caller, reference)).fetchone()
            if prior and prior[0] != case_id:
                raise KpiLedgerError("case grant cannot be rebound")
            db.execute("INSERT OR IGNORE INTO cases(caller,reference,case_id) VALUES(?,?,?)",
                       (caller, reference, case_id))
            if self._case(db, caller, reference)[0] != case_id:
                raise KpiLedgerError("case already registered with a different reference")

    def authorize(self, caller, reference):
        try:
            with self._db() as db:
                self._case(db, caller, reference)
            return caller, reference
        except KpiLedgerError:
            raise
        except Exception:
            raise CostAdmissionError from None

    def begin(self, binding, request_id, requested_model):
        caller, reference = binding
        try:
            _require_id(request_id, "request_id")
            _require_id(requested_model, "requested_model")
            with self._db() as db:
                if self._case(db, caller, reference)[1]:
                    raise KpiLedgerError("cost measurement already closed")
                db.execute("INSERT INTO requests(id,caller,reference,model) VALUES(?,?,?,?)",
                           (request_id, caller, reference, requested_model))
        except Exception:
            raise CostAdmissionError from None
        capture = _Capture(self, caller, reference, request_id)
        capture.context_reset = ACTIVE_COST.set(capture)
        return capture

    def finish(self, capture):
        """Never turn a completed paid call into a retryable telemetry error."""
        try:
            with self._db() as db:
                db.execute("UPDATE requests SET finished=1,failed=? WHERE id=?",
                           (int(capture.failed or capture.sequence == 0), capture.request_id))
            return not capture.failed and capture.sequence > 0
        except Exception:
            LOG.error("SUBLLM-COST-WRITE: result preserved; measurement remains pending")
            return False
        finally:
            ACTIVE_COST.reset(capture.context_reset)

    def _emit(self, db, caller, reference, observation):
        ledger = KpiCostLedger(self.contexts[caller])
        self._replay(ledger, observation)
        for event in ledger.events:
            self._insert_event(db, caller, reference, event)

    @staticmethod
    def _insert_event(db, caller, reference, event):
        body = _json(event)
        prior = db.execute("SELECT caller,reference,body FROM events WHERE id=?",
                           (event["event_id"],)).fetchone()
        if prior and prior != (caller, reference, body):
            raise KpiLedgerError("conflicting canonical event")
        db.execute("INSERT OR IGNORE INTO events VALUES(?,?,?,?)",
                   (event["event_id"], caller, reference, body))

    @staticmethod
    def _replay(ledger, observation):
        data, quote = observation["data"], observation["quote"]
        values = {key: value for key, value in quote.items() if key not in {"price_ref", "fx_ref"}}
        ledger.record_model_attempt(
            case_id=observation["case_id"], call_id=observation["id"],
            charge_id=observation["id"], wire_model=data["model"],
            requested_model=observation["requested_model"], duration_ms=data["duration_ms"],
            provider_status=data["provider_status"], fallback=data["sequence"] > 0,
            timestamp=observation["timestamp"], **values,
        )

    def observe(self, request_id, *, sequence, provider, model, status, duration_ms, usage):
        """Record/replay a trusted actual-attempt observation, without provider work."""
        from .usage import _count

        _require_id(provider, "provider")
        _require_id(model, "model")
        if type(sequence) is not int or sequence < 0 or status not in {"success", "error"}:
            raise KpiLedgerError("invalid attempt sequence/status")
        if type(duration_ms) is not int or duration_ms < 0:
            raise KpiLedgerError("invalid duration")
        data = {"provider": provider, "model": model, "sequence": sequence,
                "provider_status": "succeeded" if status == "success" else "failed",
                "duration_ms": duration_ms,
                "input_tokens": _count(usage, "input_tokens", "prompt_tokens"),
                "output_tokens": _count(usage, "output_tokens", "completion_tokens")}
        oid = _key(request_id, sequence)
        with self._db() as db:
            request = db.execute("SELECT caller,reference,model,finished FROM requests WHERE id=?",
                                 (request_id,)).fetchone()
            if request is None:
                raise KpiLedgerError("request has no durable admission")
            caller, reference, requested, finished = request
            case_id, closed = self._case(db, caller, reference)
            prior = db.execute("SELECT body FROM observations WHERE id=?", (oid,)).fetchone()
            if prior:
                observation = json.loads(prior[0])
                if observation["data"] != data:
                    raise KpiLedgerError("conflicting attempt replay")
                return observation
            if closed or finished:
                raise KpiLedgerError("new observation after request/case closure")
            tariff = self.tariffs.get((provider, model))
            quote = tariff.quote(data["input_tokens"], data["output_tokens"]) if tariff else {"amount": None}
            observation = {"id": oid, "request_id": request_id, "case_id": case_id,
                           "requested_model": requested, "data": data, "quote": quote, "timestamp": _utc_now()}
            self._emit(db, caller, reference, observation)
            db.execute("INSERT INTO observations VALUES(?,?,?)", (oid, request_id, _json(observation)))
            return observation

    def _ledger(self, db, caller, reference):
        case_id, closed = self._case(db, caller, reference)
        ledger = KpiCostLedger(self.contexts[caller])
        rows = db.execute("SELECT o.body FROM observations o JOIN requests r ON r.id=o.request_id "
                          "WHERE r.caller=? AND r.reference=? ORDER BY o.rowid", (caller, reference))
        for (body,) in rows:
            self._replay(ledger, json.loads(body))
        pending = db.execute("SELECT COUNT(*) FROM requests WHERE caller=? AND reference=? "
                             "AND (finished=0 OR failed=1)", (caller, reference)).fetchone()[0]
        return ledger, case_id, closed, pending

    def summary(self, caller, reference):
        with self._db() as db:
            ledger, case_id, closed, pending = self._ledger(db, caller, reference)
            result = ledger.case_cost_summary(case_id)
            result.update(closed=bool(closed), pending_request_count=pending)
            if pending:
                result.update(complete=False, total_amount_pln=None)
            return result

    def reconcile(self, caller, reference, observation_id, *, quote):
        """Trusted fee readback; requires explicit pinned tariff or billing evidence."""
        if not quote.get("price_ref"):
            raise KpiLedgerError("price provenance required")
        _require_id(quote["price_ref"], "price_ref")
        if quote.get("currency", "PLN") != "PLN":
            _require_id(quote.get("fx_ref"), "fx_ref")
        if quote.get("amount") is None:
            raise KpiLedgerError("reconciliation requires known amount")
        with self._db() as db:
            if self._case(db, caller, reference)[1]:
                raise KpiLedgerError("cost measurement already closed")
            row = db.execute("SELECT o.body FROM observations o JOIN requests r ON r.id=o.request_id "
                             "WHERE o.id=? AND r.caller=? AND r.reference=?",
                             (observation_id, caller, reference)).fetchone()
            if row is None:
                raise KpiLedgerError("observation not granted")
            observation = json.loads(row[0])
            if observation["quote"].get("amount") is not None and observation["quote"] != quote:
                raise KpiLedgerError("known quote cannot be changed")
            observation["quote"] = quote
            self._emit(db, caller, reference, observation)
            db.execute("UPDATE observations SET body=? WHERE id=?", (_json(observation), observation_id))

    def close_case_cost(self, caller, reference):
        with self._db() as db:
            ledger, case_id, closed, pending = self._ledger(db, caller, reference)
            if closed:
                return next(event for event in self._events(db, caller, reference)
                            if event["kind"] == "cost.measurement_closed")
            if pending:
                raise IncompleteCostMeasurementError("requests remain pending or observations failed")
            event = ledger.close_case_cost(case_id, event_id="closed:" + _key(caller, reference))
            self._insert_event(db, caller, reference, event)
            db.execute("UPDATE cases SET closed=1 WHERE caller=? AND reference=?", (caller, reference))
            return event

    def _events(self, db, caller, reference):
        self._case(db, caller, reference)
        return [json.loads(row[0]) for row in db.execute(
            "SELECT body FROM events WHERE caller=? AND reference=? ORDER BY rowid", (caller, reference))]

    def events(self, caller, reference):
        with self._db() as db:
            return self._events(db, caller, reference)

    def audit_records(self, caller, reference):
        with self._db() as db:
            self._case(db, caller, reference)
            return [json.loads(row[0]) for row in db.execute(
                "SELECT o.body FROM observations o JOIN requests r ON r.id=o.request_id "
                "WHERE r.caller=? AND r.reference=? ORDER BY o.rowid", (caller, reference))]

    def export_events(self, caller, reference):
        """Atomically replace this case's dedicated stream; do not append to ops logs."""
        directory = self.path.parent / "exports"
        directory.mkdir(mode=0o700, exist_ok=True)
        target = directory / (_key(caller, reference) + ".jsonl")
        with self._db() as db:
            events = self._events(db, caller, reference)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                                 delete=False) as handle:
                    temporary = handle.name
                    handle.write("".join(_json(event) + "\n" for event in events))
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, target)
                fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(fd)
                finally:
                    os.close(fd)
            finally:
                if temporary and os.path.exists(temporary):
                    os.unlink(temporary)
        return target


def record_provider_attempt(**attempt):
    """Actual-attempt seam; telemetry errors never trigger another paid attempt."""
    capture = ACTIVE_COST.get()
    if capture is None:
        return
    sequence = capture.sequence
    capture.sequence += 1
    try:
        capture.observer.observe(capture.request_id, sequence=sequence, **attempt)
    except Exception:
        capture.failed = True
        LOG.error("SUBLLM-COST-WRITE: result preserved; measurement remains pending")
