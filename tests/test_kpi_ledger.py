"""Tests for HeyAsa ops v1 cost and model-invocation ledger emitter (KPI-04)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from subllm.kpi_ledger import (
    HEYASA_OPS_SCHEMA,
    DeploymentContext,
    IncompleteCostMeasurementError,
    KpiCostLedger,
    KpiLedgerError,
)


def _ctx() -> DeploymentContext:
    return DeploymentContext(
        deployment_id="dep-pilot-01",
        workflow_id="wf.reply_draft",
        workflow_version="1.0.0",
        cohort_id="cohort-2026-11",
        source_id="subactor.subllm",
        stage="evaluation",
        synthetic=False,
    )


def test_duplicate_webhook_does_not_double_count_and_conflict_fails() -> None:
    """AC-01: Powtórzony webhook o tym samym charge_id nie podwaja kosztu."""
    ledger = KpiCostLedger(_ctx())
    ev1, created1 = ledger.record_charge(
        case_id="case_001",
        charge_id="twilio_msg_SM998877",
        category="sms",
        provider_status="delivered",
        amount="0.18",
        currency="PLN",
        pricing_source="provider_webhook",
        calculation_method="exact_webhook",
        timestamp="2026-11-11T15:00:00Z",
    )
    ev2, created2 = ledger.record_charge(
        case_id="case_001",
        charge_id="twilio_msg_SM998877",
        category="sms",
        provider_status="delivered",
        amount="0.18",
        currency="PLN",
        pricing_source="provider_webhook",
        calculation_method="exact_webhook",
        timestamp="2026-11-11T15:00:05Z",
    )

    assert created1 is True
    assert created2 is False
    assert ev1 == ev2
    assert len(ledger.events) == 1
    assert ledger.case_cost_summary("case_001")["total_amount_pln"] == "0.18"

    with pytest.raises(KpiLedgerError, match="conflicting duplicate charge_id"):
        ledger.record_charge(
            case_id="case_001",
            charge_id="twilio_msg_SM998877",
            category="sms",
            provider_status="delivered",
            amount="0.36",
            currency="PLN",
            pricing_source="provider_webhook",
            calculation_method="exact_webhook",
        )


def test_failed_and_retried_attempts_stay_in_same_case_with_fallback_model() -> None:
    """AC-02: Nieudane i ponowione próby oraz fallback modelu pozostają w kosztach tej samej sprawy."""
    ledger = KpiCostLedger(_ctx())

    inv1, cost1 = ledger.record_model_attempt(
        case_id="case_retry_01",
        call_id="call_primary_01",
        charge_id="chg_primary_01",
        requested_model="glm-5.3",
        wire_model="glm-5.3",
        duration_ms=4200,
        provider_status="failed",
        amount="0.04",
        currency="PLN",
        pricing_source="pinned_tariff",
        calculation_method="token_tariff",
        timestamp="2026-11-11T15:10:00Z",
    )
    inv2, cost2 = ledger.record_model_attempt(
        case_id="case_retry_01",
        call_id="call_fallback_02",
        charge_id="chg_fallback_02",
        requested_model="glm-5.3",
        wire_model="gpt-5.4-mini",
        duration_ms=1850,
        provider_status="succeeded",
        parameter_count=8_000_000_000,
        amount=Decimal("0.025"),
        currency="USD",
        fx_rate_to_pln=Decimal("4.00"),
        pricing_source="pinned_tariff",
        calculation_method="token_tariff",
        timestamp="2026-11-11T15:10:03Z",
    )

    assert inv1["payload"]["fallback"] is False
    assert inv1["payload"]["model_id"] == "glm-5.3"
    assert inv2["payload"]["fallback"] is True
    assert inv2["payload"]["model_id"] == "gpt-5.4-mini"
    assert cost1 is not None and cost2 is not None

    closed = ledger.close_case_cost("case_retry_01", timestamp="2026-11-11T15:10:05Z")
    assert closed is not None
    assert closed["kind"] == "cost.measurement_closed"
    assert closed["payload"] == {"complete": True}

    summary = ledger.case_cost_summary("case_retry_01")
    assert summary["complete"] is True
    assert summary["known_charge_count"] == 2
    assert summary["total_amount_pln"] == "0.14"


def test_missing_fee_marks_measurement_incomplete_never_zero() -> None:
    """AC-03: Brak danych o opłacie daje niepełny pomiar, nigdy sztuczne 0.00."""
    ledger = KpiCostLedger(_ctx())

    _, cost_ev = ledger.record_model_attempt(
        case_id="case_unknown_fee",
        call_id="call_u1",
        charge_id="chg_u1",
        wire_model="glm-5.3",
        duration_ms=900,
        provider_status="succeeded",
        amount=None,
        timestamp="2026-11-11T15:20:00Z",
    )
    assert cost_ev is None
    assert [ev["kind"] for ev in ledger.events] == ["model.invoked"]

    summary = ledger.case_cost_summary("case_unknown_fee")
    assert summary["complete"] is False
    assert summary["total_amount_pln"] is None
    assert summary["unknown_charge_ids"] == ["chg_u1"]

    assert ledger.close_case_cost("case_unknown_fee", strict=False) is None
    with pytest.raises(IncompleteCostMeasurementError):
        ledger.close_case_cost("case_unknown_fee", strict=True)

    # Implicit zero without explicit_zero=True is also rejected.
    with pytest.raises(KpiLedgerError, match="explicit_zero"):
        ledger.record_charge(
            case_id="case_unknown_fee",
            charge_id="chg_zero_guess",
            category="model",
            provider_status="succeeded",
            amount="0",
            pricing_source="pinned_tariff",
            calculation_method="token_tariff",
        )

    # Reconciling chg_u1 later via provider invoice unblocks closure.
    reconciled_ev, created = ledger.record_charge(
        case_id="case_unknown_fee",
        charge_id="chg_u1",
        category="model",
        provider_status="succeeded",
        amount="0.09",
        currency="PLN",
        pricing_source="provider_invoice",
        calculation_method="token_tariff",
        timestamp="2026-11-11T15:25:00Z",
    )
    assert created is True
    assert reconciled_ev is not None
    closed = ledger.close_case_cost("case_unknown_fee", timestamp="2026-11-11T15:25:01Z")
    assert closed is not None
    assert ledger.case_cost_summary("case_unknown_fee")["total_amount_pln"] == "0.09"


def test_currency_pricing_source_and_business_outcome_separation(tmp_path: Path) -> None:
    """AC-04 & AC-05: Waluta/źródło kwoty są wymagane, a status dostawcy nie zamyka celu biznesowego."""
    jsonl_file = tmp_path / "ops-events.jsonl"
    ledger = KpiCostLedger(_ctx(), jsonl_path=jsonl_file)

    with pytest.raises(KpiLedgerError, match="fx_rate_to_pln"):
        ledger.record_charge(
            case_id="case_fx",
            charge_id="chg_eur_1",
            category="telephony",
            provider_status="answered",
            amount="0.50",
            currency="EUR",
            pricing_source="provider_webhook",
            calculation_method="per_minute",
        )

    ev, created = ledger.record_charge(
        case_id="case_local",
        charge_id="chg_local_01",
        category="model",
        provider_status="succeeded",
        amount="0.00",
        currency="PLN",
        pricing_source="local_inference",
        calculation_method="zero_local",
        explicit_zero=True,
        wire_model="qwen2.5-local",
        timestamp="2026-11-11T15:30:00Z",
    )
    assert created is True
    assert ev is not None
    assert set(ev["payload"].keys()) == {"amount", "category", "charge_id", "currency"}
    assert ev["schema_version"] == HEYASA_OPS_SCHEMA

    ledger.close_case_cost("case_local", timestamp="2026-11-11T15:30:01Z")
    assert all(item["kind"] != "case.goal_verified" for item in ledger.events)
    assert all(rec.closes_business_goal is False for rec in ledger.audit_records)

    persisted = [json.loads(line) for line in jsonl_file.read_text(encoding="utf-8").splitlines()]
    assert [row["kind"] for row in persisted] == ["cost.recorded", "cost.measurement_closed"]
