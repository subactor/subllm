# Ticket 217: Isolate usage ingestion from route policy availability

- **ID**: ticket-217
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-14

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested continuation, tests and protected merge. Parent PLF-22390. maxActiveMinutes: 120.

A loopback collector rejects policy validation with HTTP 422. Usage ingestion currently invokes that unrelated validation and credential observation before recording metadata for an already completed provider attempt. Select an explicit metadata-only observation for RECORD_USAGE_REF; retain all other policy observations and existing strict journal/command validation. No credentials, provider calls, resolver changes, production writes or rollout.

## Acceptance criteria

- [x] AC-01: Real loopback HTTP records one validated attempt and deduplicates replay despite unavailable routing policy or credential observation.
- [ ] AC-02: Invalid metadata and unavailable journal fail closed; other process policy controls remain; full tests, governance and independent exact-head publication pass.

Local evidence: regression reproduced as 2 failures and 5 passes before the source change. After the change, 179 affected tests pass; coverage accounting passes all 61 usage tests. Full verification and independent current-head publication remain required. Existing synthetic OpenRouter fixture now uses an explicit test placeholder so the unchanged secret scanner accepts the touched test file.
