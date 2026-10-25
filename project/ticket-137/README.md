# Ticket137: Explicit recovery of an interrupted usage-index build

- **ID**: ticket-137
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: user requests autonomous continuation, immediate repairs, tests and protected merging. This is a bounded continuation of issue142 after published PR143 created9 valid indexes and one known invalid index52788 on public.interactions_20260930 after SQLSTATE55P03. No index has been dropped/rebuilt. Existing default guards stay intact; only explicit, exact-OID, matching-definition, nonunique invalid-index recovery is added and reviewed before any live repair. Session bounded120 minutes from2026-10-25T11:12Z. No new user objective or credential access is inferred.

- [x] AC-01: Reproduce an actual invalid concurrent build in a disposable PostgreSQL fixture and verify logical-definition/OID ownership guards.
- [x] AC-02: Explicit content-pinned recovery rebuilds one managed invalid nonunique leaf concurrently, preserving data and rejecting wrong OIDs, stale plans, unknown/healthy/constraint indexes and conflicting definitions; normal apply never auto-repairs or drops.
- [x] AC-03: Shared maintenance locking/settings remain bounded; DDL lock wait5000ms is distinct from the unchanged5000ms query deadline,30s statement cap and45s batch budget. Partial/interrupted state is reported, not retried or cleaned automatically.
- [ ] AC-04: Full/focused checks and protected exact-head delivery pass; then recover known index52788, resume current local archive migration and verify native query/index readback before closing issue142.

Validation:37 unit boundary cases pass; full stack (Docs/Report, Logs, Ruff, compile, pytest and build) passes. A real disposable PostgreSQL fixture creates an invalid index by canceling an actual concurrent build behind an older writer, preserves default plan/apply refusal, rejects a stale recovery pin, rebuilds the exact owned index concurrently and verifies validity plus refusal to rebuild it again once healthy. Query/payload/search/pagination parity and concurrent writes still pass. Final fixture caller-query timing2089.876ms before versus54.214ms after, not a production guarantee. The live archive remains at the preserved9 valid plus one known invalid index; no live recovery has run. Independent exact-head publication and subsequent native readback remain pending.
