# Ticket161: Keep usage writes available during panel reads

- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: ongoing user request to fix request/response visibility and test native offline integration.

## Acceptance criteria

- [x] AC-01: A held read transaction cannot discard a new usage write; preserve all historical rows and private metadata.
- [ ] AC-02: Focused storage tests, governance, exact-head OneDev and independent publication pass; no model inference replay or guessed backfill.

Regression first failed with exactly the observed journal warning and1 row instead of2 under a retained read transaction. WAL fixes this;136 storage/native/capture tests pass. Existing request payload privacy and zero-token accounting remain covered. No inference was replayed and no historical row was backfilled.
