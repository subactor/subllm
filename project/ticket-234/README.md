# Ticket 234: Support Ollama parameter scope, decision keep_alive and autonomy role context budgets

- **ID**: ticket-234
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18
- **Approval Evidence**: SESSION_EXECUTION_AUTHORIZATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: Complete `LLM-008` and `LLM-009` runtime-profile contracts cleanly in `src/subllm/runtime_profile.py` and `tests/test_runtime_profile.py` while preserving policy-routed `ollama_parameter_scope` rejection of ignored OpenAI `/v1` options (`LLM-005` cataloged native Ollama routing in `proxy.py` stays separate under `ticket-233` lease):
1. `LLM-008`: Add bounded `keep_alive` (`0..300`) support to `PARAMETERS["decision"]` and `GatewayClient.infer("decision", ...)`.
2. `LLM-009`: Support optional autonomy roles (`planner`, `selector`, `generator`) alongside core `ROLES` and enforce input+output `context_size` admission (`admit_context_budget`) before dispatch.

## Acceptance criteria

- [x] AC-01: Policy-routed `ollama_parameter_scope` preserves rejection of unsupported OpenAI `/v1` native options (`tests/test_audio_proxy.py`).
- [x] AC-02: `GatewayClient.infer("decision", ...)` validates and forwards `keep_alive` (`0..300`).
- [x] AC-03: `validate_profile` and `GatewayClient.infer` support optional `planner`, `selector`, `generator` roles and enforce `admit_context_budget` when `context_size` is configured.
- [x] AC-04: `tests/test_runtime_profile.py`, `tests/test_audio_proxy.py`, `tests/test_decisions.py`, `tests/test_generation_limits.py`, `ruff check`, `./project/governance-check.sh --base origin/main`, and `wellman check` pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
