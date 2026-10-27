# ticket-153: Exact usage archive links

- **ID**: ticket-153
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-27
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: the user requested continued SubLLM backlog repair and investigation of missing request/response details on localhost:8788. Implement and request protected publication within that objective. Runtime promotion remains separate.

- [x] AC-01: Ingest only a strict optional archive day/id reference; keep prompts, replies and credentials outside the metadata journal.
- [x] AC-02: Resolve the exact referenced private record and verify its correlation, identity and status binding; never guess historical associations. Fail closed for missing/mismatched/unavailable referenced capture.
- [x] AC-03: Preserve old journal reads without schema mutation and verify actual HTTP ingest/detail, failure isolation and reference privacy.
- [ ] AC-04: Pass governance, stack checks and exact-head protected independent publication.

The client_routes.py scope is reserved by ticket-145 and is preserved. This ticket supplies the explicit capture-link contract for instrumented callers; it does not claim old calls were linked or that the backend was restarted.

Validation: focused usage/HTTP/MCP checks passed 61 tests. The full stack check passed ['959 passed, 2 warnings in 57.45s'] in 63.73 seconds, including lint, compilation, package builds and isolated PostgreSQL tests. No production database or model call was used. Exact-head protected review remains pending.
