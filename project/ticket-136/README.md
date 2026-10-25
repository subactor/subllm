# Ticket 136: Repair caller-filtered PostgreSQL usage queries

- **ID**: ticket-136
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: user requests autonomous continuation, fixes, tests and protected merging; latest continuation follows issue142. This includes bounded additive online index maintenance on the existing local development archive after protected source delivery, using native database configuration without exposing credentials. Session bounded120 minutes from2026-10-25T10:07Z. Gemini3.8 Flash is the requested advisory model; independent protected review retains its declared profile.

- [x] AC-01: Reproduce the caller-filtered cost on a disposable partitioned archive with large messages; verify exact results, filtered pagination and full-message search.
- [x] AC-02: Existing partitions gain caller-leading indexes only through an explicit digest-bound bounded concurrent operation; stale plans, conflicts and invalid indexes fail closed without deletion. Queries retain their5000ms deadline.
- [x] AC-03: New empty partitions are indexed without adding historical backfill to provider writes; already-populated partitions are preserved until explicit maintenance.
- [ ] AC-04: Focused/full stack and governance pass, protected exact-head source merge succeeds; record bounded local migration and runtime query/index readback separately before closing issue142.

Local evidence: all24 unit boundary cases and831 full-suite cases pass, with one optional backend-discovery skip. The4 existing PostgreSQL tests pass on an explicitly bound disposable database. Two real partitioned fixtures with1500 synthetic64KiB documents preserve exact summaries, payloads, full-message search and filtered pagination. Final definition/driver fixture elapsed2500.527ms before and53.080ms after indexing; this is a fixture measurement, not a production guarantee. A fresh writer commits while concurrent index creation waits for an older writer. Ruff, compile, wheel/sdist, Docs/Report, Logs and governance pass. A mistakenly ambient existing integration test appended its synthetic pg-test-client record to the development archive and reproduced the timeout; data was preserved and an external observation records the effect. Native Gemini3.8 advisory is unavailable; no provider request occurred.

Publication and runtime boundary: the metadata-only native plan observes35 existing development archive leaves missing caller-leading indexes. No live migration has run. Independent exact-head source publication precedes bounded additive online batches and native query/index readback; issue142 remains open until those effects are verified.

Pre-publication repairs: three new cases reproduced incorrect equivalence after stripping spaces/parentheses from quoted JSON keys and function calls; all24 now pass with token-aware comparison. The initial OneDev run found the optional psycopg import during unit-test collection. Unit driver boundaries are now isolated; all24 pass with psycopg import deliberately unavailable, while the explicit fixture entrypoint still uses the real driver. Full exact-source stack validation is repeated before re-dispatch. No live migration has run.
