# Ticket 152: Reliable usage details and capture availability

- **ID**: ticket-152
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-27

SESSION_EXECUTION_AUTHORIZATION: the user requested continued backlog work and investigation of localhost:8788, token counts, actual task execution, and missing request/response details on 2026-10-27. This bounded implementation addresses detail retrieval and truthful capture state. Independent review and publication are authorized under the existing host process; deployment remains separately admitted.

- [x] AC-01: Numeric journal records are explicitly unlinked; exact archive IDs return stored payloads. Never guess associations from time or token counts.
- [x] AC-02: Archive read failure remains visible and distinguishable from an uncaptured/unlinked request; no raw driver exception enters responses.
- [x] AC-03: Every selected ID can request details. Late responses and errors cannot overwrite another selected or closed record.
- [ ] AC-04: Focused HTTP/storage and actual JavaScript DOM regressions, stack checks and governance pass; obtain independent exact-head publication.

Raw production prompts/responses stay in their existing private archive. Diagnostic receipts contain only bounded metadata, digests and counts. Cross-repository findings and the existing duplicate-review owner issue validator-agent#611 are separate from this source scope.

Validation on 2026-10-27: the full scripts/verify run passed 943 tests with two existing deprecation warnings, plus Ruff, compilation, docs/log checks and wheel/sdist builds, using a dedicated usage_test_ticket152 database (146.37 seconds). The subsequent backward-compatibility case for legacy collector responses passed with the focused HTTP/JavaScript suite: 36 tests. JavaScript tests execute the actual shipped handlers in Node with controlled network completion order; they verify numeric IDs, stale/closed selections, visible read failure and honest export coverage. Governance and git diff --check pass. No provider call was made for this qualification.

The observed localhost:8788 process imports the primary source checkout and explicitly has SUBLLM_USE_LOCAL_POSTGRES=0. Its metadata journal contains no payloads, whereas three matching private proxy archive records contain both messages and replies under different IDs/caller/model identities. These historical records must not be joined heuristically. A source merge alone does not restart a running backend or grant runtime promotion.

Related investigation: overlapping identical single-chunk review messages (same digest, three concurrent executions) were reported under existing validator-agent#611. Cross-repository report publication is retained as a bounded dependency under subactor/docs; native docs admission currently reports unassigned recovery branches and a dirty primary, which remain untouched.
