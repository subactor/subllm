# Ticket 195: Classify Anthropic billing refusals and ZAI exhausted plan limits

- **ID**: ticket-195
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the current user asks to investigate recurring
SubLLM API errors after key rotation and repair central credential use.
Parent maskservice:PLF-22275 preserves the exact reported request identifiers.
Ticket194 / PR198 is independently merged into the accepted base.

Bounded current central SubLLM probes show two additional deterministic refusals:
Anthropic returns HTTP400 invalid_request_error because API credit is exhausted;
ZAI returns HTTP429 code1310 because its weekly/monthly plan limit is exhausted.
Neither is a temporary pacing error or repaired by changing OPENAI_API_KEY.
Map only these recognized provider responses to the existing exhausted-quota
outcome, cooldown and permitted fallback. Keep other bad requests fail-closed.
Never include provider account text, credentials or arbitrary responses in
public diagnostics, and never cycle keys or reset a circuit to bypass limits.

## Acceptance criteria

- [x] AC-01: Bounded offline regressions cover both recognized refusals, provider
  context, malformed and oversized errors, ordinaryHTTP400, temporary429,
  secret-free exceptions and fallback to an already permitted provider.
- [ ] AC-02: Governance, lint and genuine native protected checks pass; independent
  Validator approves and merges the exact frozen source.
- [ ] AC-03: The reviewed immutable runtime is qualified through the existing
  owner route and its actual source/credential selection is observed.

Source scope: the two transport classifiers, Anthropic call context and their
existing two regression modules. No consumer config, key or account change.
Private diagnostic receipts remain outside this repository.

## Local validation

134 focused offline tests passed, including actual native classifier-to-fallback
and persisted cooldown behavior, plus the existing two private-gateway exchange
secrecy cases. Native full-suite feedback identified missing optional provider
metadata in those exchanges; unknown provider context now stays unclassified
instead of raising KeyError. Governance and Ruff passed. Runtime activation
and protected exact-head publication remain pending; local PASS is not approval.
