# Ticket 193: Add Codex CLI GPT-6 Luna fallback for Heyasa, Koru and supervisor routes

- **ID**: ticket-193
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user directed continuation, merge and deployment, asked why Heyasa does not use GPT-6 Luna through SubLLM, and supplied current SubLLM usage records showing `codex/gpt-6-luna` repeatedly classified as `SUBLLM-PROVIDER-RATE-LIMIT` before Koru and Supervisor fall back to Ollama. Keep the direct API candidate and add the already-supported `codex-cli/gpt-6-luna` subscription transport as a bounded fallback on Heyasa command/decision-routing, the affected Koru routes and Supervisor assessment. Preserve explicit `SUBLLM_PROVIDER_ORDER` allowlists and retain all existing safety gates and downstream fallbacks.

The write scope is limited to `src/subllm/policy.py`, `tests/test_task_model_routing.py`, and `tests/test_policy.py`, plus this ticket metadata. No credential, systemd, or consumer repository changes are included.

## Acceptance criteria

- [x] AC-01: `heyasa/command`, `heyasa/decision-routing`, `koru-agent/nl-to-koru-dsl`, `koru-agent/queue-executor`, and `supervisor/assessment` resolve `codex-cli/gpt-6-luna` as a fallback candidate while retaining `codex/gpt-6-luna`.
- [x] AC-02: With the standard operator policy and no explicit provider order, the CLI candidate is reachable after direct Codex API attempts and before the local Ollama fallback. An explicit provider allowlist that omits `codex-cli` continues to omit it.
- [x] AC-03: Regression tests cover route membership, exact model mapping, fallback ordering, and fail-closed behavior when the CLI provider is disabled or excluded.
- [ ] AC-04: Focused tests, the repository governance check, and the required independent exact-head validator pass.
- [ ] AC-05: After protected merge, the deployed SubLLM route serves one bounded, non-side-effecting canary through `codex-cli/gpt-6-luna`; the live usage ledger confirms the provider/model. Do not repeat a completed paid or quota-consuming call to repair logging.

## Dependencies and delivery

The model catalog already maps `gpt-6-luna` to both `codex` and `codex-cli`; ticket 144 previously qualified one Codex CLI canary. The live host policy enables `codex-cli`, but current Heyasa, Koru and Supervisor route membership excludes it. Protected OneDev/Validator publication and a separately observed runtime deployment remain required.

The host usage archive retains private responses. Tests and receipts must not print credentials or raw provider responses.
