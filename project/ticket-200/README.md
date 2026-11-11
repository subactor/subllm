# Ticket 200: Add HeyAsa ops v1 model and communication cost ledger emitter (KPI-04)

- **ID**: ticket-200
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-11

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user explicitly requested implementing the HeyAsa-Tellmesh rollout tasks across `heyasa`, `subactor`, and `tellmesh` (`KPI-04` cost ledger emitter in `subactor/subllm`).

Add `src/subllm/kpi_ledger.py` (re-exported in `src/subllm/__init__.py`) and `tests/test_kpi_ledger.py` to emit `heyasa.ops.v1`-conformant `model.invoked`, `cost.recorded`, and `cost.measurement_closed` events with `charge_id` deduplication, failed/retry attempt binding, unknown-fee protection, PLN currency/source locking, and strict separation of provider status from business goal completion.

## Acceptance criteria

- [x] AC-01: Duplicate provider webhooks/callbacks for the same `charge_id` are idempotent and do not double-count costs, while conflicting amounts/categories on an existing `charge_id` fail closed.
- [x] AC-02: Failed and retried attempts remain bound to the same `case_id`, emitting `model.invoked` with the actual `wire_model` and `fallback` flag.
- [x] AC-03: Missing fee data (`amount=None`) or unconfirmed zero amounts never fabricate `0.00` costs and block `cost.measurement_closed` until reconciled, while explicit local zero-cost inference (`explicit_zero=True`) is supported.
- [x] AC-04: Currency (`PLN` or locked `fx_rate_to_pln`), `pricing_source`, and `calculation_method` are validated before closure, provider status never emits `case.goal_verified`, and `pytest`, `./project/governance-check.sh --base origin/main`, and `wellman check` pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
