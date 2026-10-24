# Ticket 127: Cached API availability and priority-first failover

- **ID**: ticket-127
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: user requests efficient persisted API availability, ordered failover, and an explicit no-working-API error. Coordination STARTER-139@subactor; operator PLF-17341@dockuri remains independent. User explicitly authorized backing up and restoring only the old credential_env.py primary modification; content-addressed backup/patch and restoration receipt remain external.

Scope: adaptive.py and focused regression tests only. No credentials, model downloads, purchases, global routing-policy changes, unrelated source, stronger/format constraint weakening, direct merge or self-review.

- [x] AC-01: Failure uses the next eligible API on the actual request; no synthetic request-time sweep.
- [x] AC-02: Persisted provider cooldown is shared with ordinary routes and respected across calls/processes and formats; expiry permits a later real attempt.
- [x] AC-03: Compatible-class provider priority precedes latency/preferred historical route; a success returns immediately.
- [x] AC-04: All-unavailable outcome has a clear stable exhausted-chain code and safe bounded diagnostic; class/format/deadline constraints remain.
- [ ] AC-05: Focused/full tests and managed gate pass, then frozen exact-head OneDev/independent protected publication.

Maximum active source session: 120 minutes, initial allocation deadline 2026-10-24T20:05:44Z. Checkpoint at material boundaries; preserve all other owners.

Local evidence: 9/10 new regressions failed before the fix; 37 focused tests pass after. Complete scripts/verify passes with 690 tests against an owned disposable PostgreSQL fixture, Ruff/compile/build and managed governance pass. Shared host PostgreSQL statement timeout was isolated without changing its settings or test code. Protected review/publication is still pending; no self-approval.
