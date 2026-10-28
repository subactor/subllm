# Ticket 158: Exact SDK attempt archive attribution

- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: continue the user-requested SubLLM backlog and missing request/response investigation, now tracked by issue163. New disjoint native application scope is admitted; preserve ticket145 router ownership and every unrelated checkout.

## Acceptance criteria

- [x] AC-01: Success and failed direct SDK attempts carry an exact persisted archive id/day to the matching journal row. The shared lifecycle binds raw request identity and target metadata; no history lookup or guessed join.
- [x] AC-02: A reference is consumed once and cannot leak across mismatch, disabled capture, failed writes, nested or concurrent calls. Explicit references retain precedence. Capture/journal failure preserves the single provider result, with fixed secret-safe diagnostics.
- [ ] AC-03: Real SQLite archive/journal integration, privacy, error, nesting and concurrency regressions and required protected checks pass. No paid inference is required for qualification.
- [ ] AC-04: Independent exact-head publication and immutable SDK qualification are recorded separately from any live runtime selection. Preserve existing provider policies, budgets and unknown worktrees.

## Verification

Affected SDK, journal, gateway, proxy, routing and timeout regressions:227passed,
1existing opt-in PostgreSQL skip. Testless instrumentation repeats this affected
selection successfully and generates172 external pruning candidates; no test
was deleted. The25 new lifecycle tests plus the existing PostgreSQL query test
pass26 cases against a disposable, labelled, isolated usage_test_ database.
The fixture now waits on its mapped TCP database before testing; the initial
startup-only failure is preserved in private receipts. Ruff and native governance
pass. Full exact-head protected CI, independent review and runtime qualification
remain separate required evidence; no paid model call was used for these checks.
