# Ticket 168: Liquid AI d1-ultra offline decision routing

- **ID**: ticket-168
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-28

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested to use the local Liquid AI `d1-ultra` decision model offline within Ollama for routing and wherever appropriate, add it to `subllm` and reuse it across client libraries (heyasa, willmux, planfile).
Re-export the offline decision API (ticket-162 already admitted `d1-ultra` and `d1:3b` as explicit, unaliased local decision models) from the top-level `subllm` package so dependent libraries can reuse it with `from subllm import decide, resolve_decision_model`.

## Changes
- `src/subllm/__init__.py`: re-export `decide`, `decide_legacy`, `resolve_decision_model`, `DecisionError`, `DECISION_MODELS`, `DEFAULT_DECISION_MODEL`.
- `tests/test_decisions.py`: cover `d1-ultra` resolution, top-level exports and native-server decisions with `d1-ultra`. Unaliased, fail-closed model identity from ticket-162 is preserved (`d1-ultra:latest` stays rejected).

## Acceptance criteria

- [x] AC-01: `resolve_decision_model` accepts `d1-ultra` and `d1:3b`; unlisted names still fail closed.
- [x] AC-02: `subllm` exports `decide`, `decide_legacy`, `resolve_decision_model`, `DecisionError`, `DECISION_MODELS`, `DEFAULT_DECISION_MODEL`.
- [x] AC-03: `tests/test_decisions.py` passes.
- [x] AC-04: `./project/governance-check.sh` passes.

## Verification

- `PYTHONPATH=src pytest tests/test_decisions.py`: 57 passed.
- Governance check: `./project/governance-check.sh` passes cleanly.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
