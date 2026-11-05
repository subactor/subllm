# ticket-194: Central credential ownership and quota-aware failover

- **ID**: ticket-194
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: current user asks deep OpenAI/SubLLM detection, concrete request tables, compare keys privately, repair use of an available authorized central route, test, merge and deploy. Canonical request PLF-24992. Previous Willmux526 remains preserved under PLF-24990. Ticket193 / PR197 is already merged/deployed; this ticket owns a distinct material correction.

Two minimal live SubLLM worker probes against the same model and endpoint show: central file K1 succeeds in 1322ms; Heyasa process K2 fails HTTP429 with error.code credit_balance_exhausted and error.type insufficient_quota in 1355ms. SubLLM currently reports every HTTP429 as RATE-LIMIT, and per-process credentials override its discovered central file. Supervisor completion strips provider credentials and delegates to SubLLM. Preserve explicit operator allowlists and source/auth boundaries; do not rotate keys on errors.

## Acceptance criteria

- [x] AC-01: Explicit shared mode uses only credentials from a required validated SubLLM file, while process-first default and isolated explicit environments remain compatible.
- [x] AC-02: Bounded quota-code classification distinguishes exhausted credit from temporary HTTP429 without leaking arbitrary provider text or credentials; exhausted quota is cooled and not probed as transient last resort.
- [x] AC-03: Recognized transient CLI errors continue to another permitted candidate inside the same deadline; format/contract failures remain fail-closed and explicit model/provider restrictions hold.
- [ ] AC-04: Focused regression, governance, protected OneDev/Validator merge and observed central runtime activation pass; a bounded post-deployment canary confirms the exact service credential source.

## Evidence

Host-private detection receipts live in `.subactor/receipts/api-routing-detection-20261105/`; keys are represented only by equality groups. The shared credential file remains untracked and is never copied into reports or source.

## Validation

All 97 focused credential/worker/cooldown/client tests pass. The previous main fails 16 of the 22 initial regression cases. Ruff and governance pass. Protected OneDev/Validator and qualified runtime activation remain required.
