# Ticket 234: Support Ollama parameter scope, decision keep_alive and autonomy role context budgets

- **ID**: ticket-234
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18
- **Approval Evidence**: SESSION_EXECUTION_AUTHORIZATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: Complete `LLM-005`, `LLM-008`, and `LLM-009` runtime-profile contracts cleanly in `src/subllm/runtime_profile.py` and `tests/test_runtime_profile.py`:
1. `LLM-005`: Make `ollama_parameter_scope` pass validated `num_ctx`/`top_k`/`repeat_penalty` options through to Ollama routes without hitting OpenAI `request_parameter_scope` errors.
2. `LLM-008`: Add bounded `keep_alive` (`0..300`) support to `PARAMETERS["decision"]` and `GatewayClient.infer("decision", ...)`.
3. `LLM-009`: Support optional autonomy roles (`planner`, `selector`, `generator`) alongside core `ROLES` and enforce input+output `context_size` admission before dispatch.

## Acceptance criteria

- [ ] AC-01: `ollama_parameter_scope` preserves `num_ctx`, `top_k`, `repeat_penalty` on Ollama routes while rejecting them on non-Ollama routes and in `request_parameter_scope`.
- [ ] AC-02: `GatewayClient.infer("decision", ...)` validates and forwards `keep_alive` (`0..300`).
- [ ] AC-03: `validate_profile` and `GatewayClient.infer` support optional `planner`, `selector`, `generator` roles and enforce `admit_context_budget` when `context_size` is configured.
- [ ] AC-04: `tests/test_runtime_profile.py`, `tests/test_decisions.py`, `tests/test_generation_limits.py`, `./project/governance-check.sh --base origin/main`, and `wellman check` pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
