# Ticket138: Preserve interrupted index artifacts with bounded replacement

- **ID**: ticket-138
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: user requests continued autonomous fixes, testing and protected merging. This is a new bounded material follow-up to published tickets136/137 and issue142; both prior source leases are released and no matching linked checkout exists. Session begins2026-10-25T12:19Z, maximum120 active minutes. Preserve exact invalid index52892 and artifact52899 on public.interactions_20261002, all data and existing5000ms query deadline. No destructive cleanup or unknown-object operation is authorized.

- [x] AC-01: Reproduce real concurrent create/reindex interruption and invalid artifact in an owned fixture; validate exact OIDs, owners, definitions and stale plans.
- [x] AC-02: Explicit additive replacement preserves both interrupted objects and all rows, rejects healthy/constraint/conflicting/active/unknown artifacts and accepts readback only for the exact deterministic valid equivalent.
- [x] AC-03: Optional maintenance budget is digest-bound and capped120s; defaults and query5000ms stay intact, no partial-budget batch item begins, no auto repair/retry/cleanup occurs.
- [ ] AC-04: Focused/full stack/governance and independent exact-head delivery pass; then exact live replacement, remaining archive indexing and native query readback succeed before issue142 closes.

Validation:62 focused unit cases pass. The full stack, governance, Ruff, compile and sdist/wheel build pass. Owned PostgreSQL fixtures reproduce genuine concurrent CREATE/REINDEX interruptions, preserve original and _ccnew OIDs, reject mismatched/stale plans and build an exact equivalent without touching either object or row content. A separate1GiB synthetic-document fixture completes its index in13095.883ms with the explicitly requested120s cap. Query/payload/search/pagination parity and concurrent writes pass. Shared archive is freshly observed at11/35 ready and unchanged; live replacement and native readback remain pending protected exact-head publication.
