"""HeyAsa ops v1 cost and model-invocation ledger emitter for SubLLM (KPI-04).

Emits schema-conformant `heyasa.ops.v1` events (`model.invoked`, `cost.recorded`,
`cost.measurement_closed`) while maintaining an auditable reconciliation log:
- Deduplicates repeated provider webhooks/callbacks by `charge_id` (rejecting
  conflicting amounts or categories on the same `charge_id`).
- Binds failed and retried provider/channel attempts to the originating business `case_id`
  and reports the actually executed `wire_model` and `fallback` flag.
- Never substitutes `0.00` for missing or unknown fees: missing fee data marks the
  case cost measurement incomplete so `cost.measurement_closed` cannot be emitted.
- Locks currency (`PLN`), `pricing_source`, and `calculation_method` before closure,
  supporting deterministic FX conversion only when an explicit `fx_rate_to_pln` is given.
- Keeps provider/transport statuses strictly separated from business goal verification
  (never emits `case.goal_verified`).
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any

HEYASA_OPS_SCHEMA = "heyasa.ops.v1"
COST_CATEGORIES: tuple[str, ...] = ("model", "tool", "infra_variable", "telephony", "sms")
OPS_STAGES: tuple[str, ...] = ("live", "evaluation", "calibration")
PRICING_SOURCES: tuple[str, ...] = (
    "provider_invoice",
    "provider_webhook",
    "pinned_tariff",
    "local_inference",
)
CALCULATION_METHODS: tuple[str, ...] = (
    "token_tariff",
    "per_minute",
    "per_segment",
    "exact_webhook",
    "zero_local",
)
PROVIDER_STATUSES: tuple[str, ...] = (
    "succeeded",
    "failed",
    "timeout",
    "rate_limited",
    "delivered",
    "answered",
    "undelivered",
)

_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,160}$")
_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
_QUANT = Decimal("0.000001")


class KpiLedgerError(ValueError):
    """Raised when a KPI cost or model invocation record violates KPI-04 rules."""


class IncompleteCostMeasurementError(KpiLedgerError):
    """Raised when attempting to close cost measurement for a case with unknown fees."""


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID_RE.fullmatch(value):
        raise KpiLedgerError(f"invalid {name}: {value!r}")
    return value


def _require_timestamp(value: str | None) -> str:
    if value is None:
        return _utc_now()
    if not isinstance(value, str) or not value.strip():
        raise KpiLedgerError("timestamp must be a non-empty ISO-8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise KpiLedgerError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise KpiLedgerError(f"timestamp requires explicit timezone: {value!r}")
    return value


def _parse_non_negative_decimal(value: str | int | float | Decimal, name: str) -> Decimal:
    if isinstance(value, bool):
        raise KpiLedgerError(f"{name} must not be boolean")
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise KpiLedgerError(f"invalid decimal {name}: {value!r}") from exc
    if not dec.is_finite() or dec < Decimal("0"):
        raise KpiLedgerError(f"{name} must be finite and >= 0, got {value!r}")
    return dec


def _format_pln(amount: Decimal) -> str:
    quantized = amount.quantize(_QUANT, rounding=ROUND_HALF_UP)
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text if "." in text else f"{text}.00"


@dataclass(frozen=True, slots=True)
class DeploymentContext:
    """Immutable deployment context required on every heyasa.ops.v1 event."""

    deployment_id: str
    workflow_id: str
    workflow_version: str
    cohort_id: str
    source_id: str = "subactor.subllm"
    stage: str = "live"
    synthetic: bool = False

    def __post_init__(self) -> None:
        for field_name in ("deployment_id", "workflow_id", "workflow_version", "cohort_id", "source_id"):
            _require_id(getattr(self, field_name), field_name)
        if self.stage not in OPS_STAGES:
            raise KpiLedgerError(f"invalid stage: {self.stage!r}; expected {OPS_STAGES}")
        if not isinstance(self.synthetic, bool):
            raise KpiLedgerError("synthetic must be a boolean")


@dataclass(frozen=True, slots=True)
class CostAuditRecord:
    """Reconciliation metadata kept alongside heyasa.ops.v1 events (never closes business goal)."""

    case_id: str
    charge_id: str
    category: str
    amount_pln: str | None
    original_currency: str
    pricing_source: str | None
    calculation_method: str | None
    provider_status: str
    wire_model: str | None
    requested_model: str | None
    fallback: bool
    closes_business_goal: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "charge_id": self.charge_id,
            "category": self.category,
            "amount_pln": self.amount_pln,
            "original_currency": self.original_currency,
            "pricing_source": self.pricing_source,
            "calculation_method": self.calculation_method,
            "provider_status": self.provider_status,
            "wire_model": self.wire_model,
            "requested_model": self.requested_model,
            "fallback": self.fallback,
            "closes_business_goal": False,
        }


class KpiCostLedger:
    """Stateful, idempotent emitter for KPI-04 model, telephony, and SMS charges."""

    def __init__(self, context: DeploymentContext, *, jsonl_path: str | Path | None = None) -> None:
        self._context = context
        self._jsonl_path = Path(jsonl_path) if jsonl_path is not None else None
        self._lock = threading.Lock()
        self._charges: dict[str, tuple[str, str, str]] = {}
        self._unknown_charges_by_case: dict[str, set[str]] = {}
        self._known_charges_by_case: dict[str, list[Decimal]] = {}
        self._closed_cases: set[str] = set()
        self._events: list[dict[str, Any]] = []
        self._audit_records: list[CostAuditRecord] = []

    @property
    def events(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._events]

    @property
    def audit_records(self) -> list[CostAuditRecord]:
        with self._lock:
            return list(self._audit_records)

    def _emit_locked(self, event: dict[str, Any]) -> None:
        self._events.append(event)
        if self._jsonl_path is not None:
            self._jsonl_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with self._jsonl_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, ensure_ascii=False) + "\n")

    def _envelope(
        self,
        *,
        event_id: str,
        case_id: str,
        kind: str,
        timestamp: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "schema_version": HEYASA_OPS_SCHEMA,
            "event_id": _require_id(event_id, "event_id"),
            "deployment_id": self._context.deployment_id,
            "case_id": _require_id(case_id, "case_id"),
            "workflow_id": self._context.workflow_id,
            "workflow_version": self._context.workflow_version,
            "cohort_id": self._context.cohort_id,
            "source_id": self._context.source_id,
            "timestamp": timestamp,
            "stage": self._context.stage,
            "synthetic": self._context.synthetic,
            "kind": kind,
            "payload": payload,
        }

    def _resolve_pln_amount(
        self,
        *,
        amount: str | int | float | Decimal | None,
        currency: str,
        fx_rate_to_pln: str | Decimal | None,
        pricing_source: str | None,
        calculation_method: str | None,
        explicit_zero: bool,
    ) -> str | None:
        if not isinstance(currency, str) or not _CURRENCY_RE.fullmatch(currency):
            raise KpiLedgerError(f"invalid ISO-4217 currency: {currency!r}")
        if amount is None:
            return None
        if pricing_source not in PRICING_SOURCES:
            raise KpiLedgerError(f"pricing_source must be locked to {PRICING_SOURCES}, got {pricing_source!r}")
        if calculation_method not in CALCULATION_METHODS:
            raise KpiLedgerError(
                f"calculation_method must be locked to {CALCULATION_METHODS}, got {calculation_method!r}"
            )
        raw_dec = _parse_non_negative_decimal(amount, "amount")
        if raw_dec == Decimal("0") and not explicit_zero:
            raise KpiLedgerError(
                "zero amount requires explicit_zero=True (e.g. local inference); pass amount=None when fee is unknown"
            )
        if currency == "PLN":
            if fx_rate_to_pln is not None:
                parsed_fx = _parse_non_negative_decimal(fx_rate_to_pln, "fx_rate_to_pln")
                if parsed_fx != Decimal("1"):
                    raise KpiLedgerError("PLN currency cannot use non-unit fx_rate_to_pln")
            pln_dec = raw_dec
        else:
            if fx_rate_to_pln is None:
                raise KpiLedgerError(f"non-PLN currency {currency} requires explicit fx_rate_to_pln")
            rate = _parse_non_negative_decimal(fx_rate_to_pln, "fx_rate_to_pln")
            if rate <= Decimal("0"):
                raise KpiLedgerError("fx_rate_to_pln must be > 0")
            pln_dec = raw_dec * rate
        return _format_pln(pln_dec)

    def record_charge(
        self,
        *,
        case_id: str,
        charge_id: str,
        category: str,
        provider_status: str,
        amount: str | int | float | Decimal | None,
        currency: str = "PLN",
        fx_rate_to_pln: str | Decimal | None = None,
        pricing_source: str | None = None,
        calculation_method: str | None = None,
        explicit_zero: bool = False,
        timestamp: str | None = None,
        wire_model: str | None = None,
        requested_model: str | None = None,
        fallback: bool = False,
    ) -> tuple[dict[str, Any] | None, bool]:
        """Record a model, tool, telephony, or SMS charge idempotently by `charge_id`.

        Returns `(cost_event_or_none, created_new)`. When `amount is None`, no synthetic
        `0.00` event is emitted and the case is marked incomplete until reconciled.
        """
        _require_id(case_id, "case_id")
        _require_id(charge_id, "charge_id")
        if category not in COST_CATEGORIES:
            raise KpiLedgerError(f"invalid category: {category!r}; expected {COST_CATEGORIES}")
        if provider_status not in PROVIDER_STATUSES:
            raise KpiLedgerError(f"invalid provider_status: {provider_status!r}; expected {PROVIDER_STATUSES}")
        stamp = _require_timestamp(timestamp)
        pln_str = self._resolve_pln_amount(
            amount=amount,
            currency=currency,
            fx_rate_to_pln=fx_rate_to_pln,
            pricing_source=pricing_source,
            calculation_method=calculation_method,
            explicit_zero=explicit_zero,
        )

        with self._lock:
            if case_id in self._closed_cases:
                raise KpiLedgerError(f"cost measurement already closed for case_id={case_id!r}")

            if charge_id in self._charges:
                prev_case, prev_cat, prev_amt = self._charges[charge_id]
                if pln_str is None or (prev_case, prev_cat, prev_amt) != (case_id, category, pln_str):
                    raise KpiLedgerError(f"conflicting duplicate charge_id={charge_id!r}")
                existing = next(
                    ev
                    for ev in self._events
                    if ev["kind"] == "cost.recorded" and ev["payload"]["charge_id"] == charge_id
                )
                return dict(existing), False

            if pln_str is None:
                self._unknown_charges_by_case.setdefault(case_id, set()).add(charge_id)
                self._audit_records.append(
                    CostAuditRecord(
                        case_id=case_id,
                        charge_id=charge_id,
                        category=category,
                        amount_pln=None,
                        original_currency=currency,
                        pricing_source=pricing_source,
                        calculation_method=calculation_method,
                        provider_status=provider_status,
                        wire_model=wire_model,
                        requested_model=requested_model,
                        fallback=bool(fallback),
                    )
                )
                return None, False

            # Reconcile if this charge_id was previously pending/unknown on the same case.
            if charge_id in self._unknown_charges_by_case.get(case_id, set()):
                self._unknown_charges_by_case[case_id].discard(charge_id)

            self._charges[charge_id] = (case_id, category, pln_str)
            self._known_charges_by_case.setdefault(case_id, []).append(Decimal(pln_str))
            event = self._envelope(
                event_id=f"cost:{charge_id}",
                case_id=case_id,
                kind="cost.recorded",
                timestamp=stamp,
                payload={
                    "amount": pln_str,
                    "category": category,
                    "charge_id": charge_id,
                    "currency": "PLN",
                },
            )
            self._emit_locked(event)
            self._audit_records.append(
                CostAuditRecord(
                    case_id=case_id,
                    charge_id=charge_id,
                    category=category,
                    amount_pln=pln_str,
                    original_currency=currency,
                    pricing_source=pricing_source,
                    calculation_method=calculation_method,
                    provider_status=provider_status,
                    wire_model=wire_model,
                    requested_model=requested_model,
                    fallback=bool(fallback),
                )
            )
            return dict(event), True

    def record_model_attempt(
        self,
        *,
        case_id: str,
        call_id: str,
        charge_id: str,
        wire_model: str,
        duration_ms: int | float,
        provider_status: str,
        requested_model: str | None = None,
        fallback: bool | None = None,
        parameter_count: int | None = None,
        amount: str | int | float | Decimal | None = None,
        currency: str = "PLN",
        fx_rate_to_pln: str | Decimal | None = None,
        pricing_source: str | None = None,
        calculation_method: str | None = None,
        explicit_zero: bool = False,
        timestamp: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        """Emit `model.invoked` with actual `wire_model` and `fallback`, plus optional `cost.recorded`."""
        _require_id(case_id, "case_id")
        _require_id(call_id, "call_id")
        _require_id(wire_model, "wire_model")
        if requested_model is not None:
            _require_id(requested_model, "requested_model")
        if isinstance(duration_ms, bool) or duration_ms < 0:
            raise KpiLedgerError(f"invalid duration_ms: {duration_ms!r}")
        if parameter_count is not None and (isinstance(parameter_count, bool) or parameter_count < 1):
            raise KpiLedgerError(f"invalid parameter_count: {parameter_count!r}")
        is_fallback = bool(fallback) if fallback is not None else (
            requested_model is not None and requested_model != wire_model
        )
        stamp = _require_timestamp(timestamp)

        with self._lock:
            invoked_event = self._envelope(
                event_id=f"model:{call_id}",
                case_id=case_id,
                kind="model.invoked",
                timestamp=stamp,
                payload={
                    "call_id": call_id,
                    "duration_ms": duration_ms,
                    "fallback": is_fallback,
                    "model_id": wire_model,
                    "parameter_count": parameter_count,
                },
            )
            self._emit_locked(invoked_event)

        cost_event, _ = self.record_charge(
            case_id=case_id,
            charge_id=charge_id,
            category="model",
            provider_status=provider_status,
            amount=amount,
            currency=currency,
            fx_rate_to_pln=fx_rate_to_pln,
            pricing_source=pricing_source,
            calculation_method=calculation_method,
            explicit_zero=explicit_zero,
            timestamp=stamp,
            wire_model=wire_model,
            requested_model=requested_model,
            fallback=is_fallback,
        )
        return invoked_event, cost_event

    def case_cost_summary(self, case_id: str) -> dict[str, Any]:
        """Inspect current cost completeness and total PLN for a business case."""
        _require_id(case_id, "case_id")
        with self._lock:
            unknown = sorted(self._unknown_charges_by_case.get(case_id, set()))
            known = self._known_charges_by_case.get(case_id, [])
            complete = not unknown and len(known) > 0
            total = _format_pln(sum(known, Decimal("0"))) if complete else None
            return {
                "case_id": case_id,
                "complete": complete,
                "closed": case_id in self._closed_cases,
                "known_charge_count": len(known),
                "unknown_charge_ids": unknown,
                "total_amount_pln": total,
                "business_goal_verified": None,
            }

    def close_case_cost(
        self,
        case_id: str,
        *,
        timestamp: str | None = None,
        allow_empty_explicit_zero: bool = False,
        strict: bool = True,
        event_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Emit `cost.measurement_closed` only when all recorded attempts have known fees."""
        _require_id(case_id, "case_id")
        if event_id is not None:
            _require_id(event_id, "event_id")
        stamp = _require_timestamp(timestamp)
        with self._lock:
            unknown = sorted(self._unknown_charges_by_case.get(case_id, set()))
            known = self._known_charges_by_case.get(case_id, [])
            if unknown or (not known and not allow_empty_explicit_zero):
                if strict:
                    raise IncompleteCostMeasurementError(
                        f"cannot close cost measurement for {case_id!r}; unknown={unknown}, known={len(known)}"
                    )
                return None
            if case_id in self._closed_cases:
                return next(
                    ev
                    for ev in self._events
                    if ev["case_id"] == case_id and ev["kind"] == "cost.measurement_closed"
                )
            self._closed_cases.add(case_id)
            closed_event = self._envelope(
                event_id=event_id if event_id is not None else f"cost-closed:{case_id}",
                case_id=case_id,
                kind="cost.measurement_closed",
                timestamp=stamp,
                payload={"complete": True},
            )
            self._emit_locked(closed_event)
            return dict(closed_event)
