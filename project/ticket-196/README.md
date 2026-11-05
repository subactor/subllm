# Ticket 196: Control compilation through central SubLLM

- **ID**: ticket-196
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requests continuation, tests, protected merge and deployment; services should call SubLLM directly with central credential and availability selection. Canonical PLF-25177 is the authenticated request; it blocks the already source-merged Platform rollout PLF-25166. The configured legacy llm-gateway is absent; do not restore an independent stale provider router or borrow another caller token.

Expose the existing Control /compile contract on the central gateway under an explicit per-client named-route grant. Reuse central archived completion, schema validation and failover. Actual response provider/model/id must remain observable. Model preference is advisory; the selected central route owns fallback. Native source delivery is isolated from guarded runtime activation.

## Acceptance criteria

- [x] AC-01: Explicitly granted authenticated clients compile through the configured central named route, with actual provider/model/id and isolated private archive preserved.
- [x] AC-02: Invalid schemas, unregistered routes, unsupported fields and unauthorized callers fail before any paid request. Provider failures remain bounded, sanitized and never invoke a local direct fallback. Focused/full/governance checks pass.
- [ ] AC-03: Independent exact-head review and merge complete before staging any new source. Dedicated least-privilege Control enrollment and trusted transport are verified; no running consumer activation precedes a real structured call.

## Verification

Host-private receipts: `.subactor/receipts/control-structured-api-20261105/`. The original source failed 25 newly added compile cases. Gateway and full checks now pass. The first full run had one unchanged MCP stdio startup timeout; all eight stdio tests and the complete declared verification subsequently passed without source/test relaxation. Keep both attempts as evidence. Global Control URL is unchanged: its other typed gateway routes require a separately owned compatibility adapter before consumer activation.
