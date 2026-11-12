import json
import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from subllm.kpi_ledger import DeploymentContext, IncompleteCostMeasurementError, KpiLedgerError
from subllm.kpi_usage import (
    ACTIVE_COST,
    CostAdmissionError,
    GatewayCostObserver,
    TokenTariff,
    record_provider_attempt,
)

CONTEXT = DeploymentContext("deployment", "workflow", "1", "cohort", stage="evaluation", synthetic=True)
TARIFF = TokenTariff("2", "4", "tariff-2026-11-12", "USD", "4.25", "fx-2026-11-12")
ATTEMPT = dict(provider="codex", model="wire-model", status="success", duration_ms=17,
               usage={"prompt_tokens": 1000, "completion_tokens": 2000})


def observer(tmp_path, tariffs=None):
    result = GatewayCostObserver(tmp_path / "private" / "cost.sqlite", {"alice": CONTEXT, "bob": CONTEXT},
                                 tariffs if tariffs is not None else {("codex", "wire-model"): TARIFF})
    result.register_case("alice", "opaque-a", "a" * 160)
    result.register_case("bob", "opaque-b", "case-b")
    return result


def admitted(result, request_id="request-1", reference="opaque-a", caller="alice"):
    return result.begin(result.authorize(caller, reference), request_id, "heyasa/command")


def test_pinned_fx_replay_restart_and_atomic_export(tmp_path):
    result = observer(tmp_path)
    capture = admitted(result)
    record_provider_attempt(**ATTEMPT)
    assert result.finish(capture)
    original = result.audit_records("alice", "opaque-a")[0]
    assert original["quote"]["fx_ref"] == TARIFF.fx_ref
    assert original["quote"]["price_ref"] == TARIFF.price_ref
    assert result.summary("alice", "opaque-a")["total_amount_pln"] == "0.0425"
    restarted = observer(tmp_path, {("codex", "wire-model"): replace(TARIFF, input_per_million="999")})
    assert restarted.observe("request-1", sequence=0, **ATTEMPT) == original
    with pytest.raises(KpiLedgerError, match="conflicting attempt replay"):
        restarted.observe("request-1", sequence=0, **{**ATTEMPT, "duration_ms": 18})
    closed = restarted.close_case_cost("alice", "opaque-a")
    assert restarted.close_case_cost("alice", "opaque-a") == closed
    assert restarted.summary("alice", "opaque-a")["closed"]
    events = restarted.events("alice", "opaque-a")
    assert [ev["kind"] for ev in events] == ["model.invoked", "cost.recorded", "cost.measurement_closed"]
    assert all(ev["case_id"] == "a" * 160 and len(ev["event_id"]) <= 160 for ev in events)
    target = restarted.export_events("alice", "opaque-a")
    assert [json.loads(line) for line in target.read_text().splitlines()] == events
    assert restarted.export_events("alice", "opaque-a").read_bytes() == target.read_bytes()
    assert stat.S_IMODE(target.stat().st_mode) == stat.S_IMODE(result.path.stat().st_mode) == 0o600
    with pytest.raises(CostAdmissionError):
        admitted(restarted, "request-2")


@pytest.mark.parametrize("tariffs,usage", [({}, ATTEMPT["usage"]),
                                          (None, {}), (None, {"input_tokens": 3}),
                                          (None, {"input_tokens": True, "output_tokens": 2})])
def test_unknown_fees_block_closure_until_explicit_readback(tmp_path, tariffs, usage):
    result = observer(tmp_path, tariffs)
    capture = admitted(result)
    record_provider_attempt(**{**ATTEMPT, "usage": usage, "status": "error"})
    assert result.finish(capture)
    summary = result.summary("alice", "opaque-a")
    assert not summary["complete"] and summary["total_amount_pln"] is None
    assert summary["known_charge_count"] == 0 and len(summary["unknown_charge_ids"]) == 1
    assert [e["kind"] for e in result.events("alice", "opaque-a")] == ["model.invoked"]
    with pytest.raises(IncompleteCostMeasurementError):
        result.close_case_cost("alice", "opaque-a")
    oid = result.audit_records("alice", "opaque-a")[0]["id"]
    quote = dict(amount="0.12", currency="USD", fx_rate_to_pln="4.25", fx_ref="fx-billing-day",
                 price_ref="invoice-1", pricing_source="provider_invoice", calculation_method="exact_webhook")
    with pytest.raises(KpiLedgerError):
        result.reconcile("bob", "opaque-b", oid, quote=quote)
    result.reconcile("alice", "opaque-a", oid, quote=quote)
    result.reconcile("alice", "opaque-a", oid, quote=quote)
    assert result.summary("alice", "opaque-a")["total_amount_pln"] == "0.51"
    assert len(result.events("alice", "opaque-a")) == 2
    with pytest.raises(KpiLedgerError, match="known quote"):
        result.reconcile("alice", "opaque-a", oid, quote={**quote, "amount": "10"})
    result.close_case_cost("alice", "opaque-a")
    assert not any(ev["kind"] == "case.goal_verified" for ev in result.events("alice", "opaque-a"))


def test_pending_and_lost_observation_survive_restart_without_releasing_cost(tmp_path, monkeypatch):
    result = observer(tmp_path)
    capture = admitted(result)
    record_provider_attempt(**ATTEMPT)
    # Observe the durable state as if the worker died before finish().
    assert observer(tmp_path).summary("alice", "opaque-a")["pending_request_count"] == 1
    with pytest.raises(IncompleteCostMeasurementError):
        observer(tmp_path).close_case_cost("alice", "opaque-a")
    assert result.finish(capture)
    capture = admitted(result, "request-2")
    with monkeypatch.context() as patch:
        patch.setattr(result, "observe", lambda *a, **k: (_ for _ in ()).throw(OSError("private failure")))
        record_provider_attempt(**ATTEMPT)
    assert not result.finish(capture)
    assert ACTIVE_COST.get() is None
    assert not observer(tmp_path).summary("alice", "opaque-a")["complete"]
    with pytest.raises(IncompleteCostMeasurementError):
        observer(tmp_path).close_case_cost("alice", "opaque-a")


def test_no_attempt_or_failed_finish_is_not_complete(tmp_path, monkeypatch):
    result = observer(tmp_path)
    capture = admitted(result)
    assert not result.finish(capture)
    capture = admitted(result, "request-2")
    record_provider_attempt(**ATTEMPT)
    with monkeypatch.context() as patch:
        patch.setattr(result, "_db", lambda: (_ for _ in ()).throw(OSError()))
        assert not result.finish(capture)
    assert ACTIVE_COST.get() is None
    assert result.summary("alice", "opaque-a")["pending_request_count"] == 2


def test_caller_grants_are_immutable_and_foreign_refs_rejected(tmp_path):
    result = observer(tmp_path)
    result.register_case("alice", "opaque-a", "a" * 160)
    for caller, reference in [("bob", "opaque-a"), ("alice", "opaque-b"), ("unknown", "opaque-a")]:
        with pytest.raises(KpiLedgerError):
            result.authorize(caller, reference)
        with pytest.raises(KpiLedgerError):
            result.events(caller, reference)
    with pytest.raises(KpiLedgerError):
        result.register_case("alice", "opaque-a", "other-case")
    with pytest.raises(KpiLedgerError):
        result.register_case("alice", "another-reference", "a" * 160)
    with pytest.raises(KpiLedgerError, match="deployment context"):
        GatewayCostObserver(result.path, {"alice": replace(CONTEXT, deployment_id="foreign")})
    capture = admitted(result)
    assert not result.finish(capture)
    with pytest.raises(CostAdmissionError):
        admitted(result)  # Accounting replay must not readmit paid work.
    with pytest.raises(KpiLedgerError):
        result.observe("not-admitted", sequence=0, **ATTEMPT)


def test_concurrent_delivery_deduplicates_events_and_isolates_contexts(tmp_path):
    result = observer(tmp_path)
    capture = admitted(result)
    with ThreadPoolExecutor(max_workers=2) as pool:
        receipts = list(pool.map(lambda _: result.observe("request-1", sequence=0, **ATTEMPT), range(4)))
    assert all(receipt == receipts[0] for receipt in receipts)
    record_provider_attempt(**ATTEMPT)  # Reuses the first observation.
    assert result.finish(capture)
    assert len(result.events("alice", "opaque-a")) == 2

    def run(caller, reference, rid):
        cap = admitted(result, rid, reference, caller)
        record_provider_attempt(**ATTEMPT)
        assert result.finish(cap)
        assert ACTIVE_COST.get() is None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run, "alice", "opaque-a", "request-2"),
                   pool.submit(run, "bob", "opaque-b", "request-b")]
        for future in futures:
            future.result(timeout=60)
    assert result.summary("alice", "opaque-a")["known_charge_count"] == 2
    assert result.summary("bob", "opaque-b")["known_charge_count"] == 1
    assert all(ev["case_id"] == "case-b" for ev in result.events("bob", "opaque-b"))


@pytest.mark.parametrize("changes", [{"input_per_million": "NaN"}, {"output_per_million": "-1"},
                                      {"fx_rate_to_pln": None}, {"fx_ref": None},
                                      {"fx_rate_to_pln": "0"}, {"currency": "BAD!"}])
def test_invalid_tariff_rejected_before_paid_work(changes):
    with pytest.raises(KpiLedgerError):
        replace(TARIFF, **changes)


def test_explicit_zero_local_tariff_is_known_not_missing(tmp_path):
    result = observer(tmp_path, {("codex", "wire-model"): TokenTariff("0", "0", "local-zero-v1")})
    capture = admitted(result)
    record_provider_attempt(**ATTEMPT)
    assert result.finish(capture)
    assert result.summary("alice", "opaque-a")["total_amount_pln"] == "0.00"
    result.close_case_cost("alice", "opaque-a")
