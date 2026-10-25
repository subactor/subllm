# Ticket146: Correct usage-storage HTTP errors and isolate database validation

- **ID**: ticket-146
- **Owner**: agent:codex / codex-subllm146-20261025t2211
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application
- **Created**: 2026-10-25
- **maxActiveMinutes**: 120

SESSION_EXECUTION_AUTHORIZATION: the user requested autonomous continuation, correction of encountered defects, tests and protected merging. The2026-10-25 continuation authorizes this bounded telemetry repair and its independent publication. Session starts2026-10-25T22:11Z, maximum120minutes.

## Goal and scope

Return HTTP503 for the existing USAGE-STORAGE-001 ingestion failure; preserve400 for invalid commands and the existing bounded error body. The integration suite must use an explicitly selected loopback usage_test_ database and must never inherit application database settings or automatic local development detection. Scope is four source/test files, two components and one corrected HTTP behavior. No telemetry retry, provider replay, dependency change, running-service activation or shared-database cleanup.

## Acceptance criteria

- [x] AC-01: A loopback HTTP fixture proves failed ingestion returns503, emits no completed usage event, and a later explicit submission succeeds after journal recovery; malformed ingestion remains400. The unchanged handler fails this regression.
- [ ] AC-02: Focused/full stack and governance checks pass; OneDev and independent exact-head Validator review precede controller merge.
- [x] AC-03: Tests disable implicit application/local PostgreSQL selection. Explicit loopback test database opt-in works; malformed, remote, service-based and non-test targets are rejected before connection. Full integration validation runs on an owned disposable PostgreSQL fixture.

## Evidence

Tracking issue: https://github.com/subactor/subllm/issues/151

External receipts: subllm-http-storage-20261025t2211. Reproduction uses an isolated invalid SQLite file. The first full-stack run exposed pre-existing implicit shared PostgreSQL selection and its unscoped-search timeout; no shared records or index definitions were removed. The bounded test-isolation scope decision, former invalid XS30 classification, native lease transitions, owned fixture identity and before/after tests are retained externally. S30 reflects the same bounded outcome; all numerical limits remain within the adopted S profile.

Validation:915 tests pass with zero skips against the owned PostgreSQL fixture; Docs/Logs, Ruff, compile and wheel/sdist build pass through Wellman. The default-no-database focused run passes54 tests with the existing integration test skipped until explicit fixture opt-in. Independent publication remains pending.

The independently published PR150 routing base is integrated using its already observed source head a6221087cff67437bb8ce1305472d530b014dd37 (tree identical to main383e1fb). The original published e71a318 history is preserved. Optional ticket-index edits are omitted to avoid parallel carrier conflicts. An intermittent unchanged SQLite test budget failure is tracked in issue153; the final full verification passes without changing the5s runtime budget or retrying provider work.

Independent CI follow-up: fixture URI validation now uses only the standard library, rejects query/authority/control-character overrides, and has a regression with psycopg imports blocked. The former validator fails that controlled absence while the corrected validator succeeds. Final local full stack:915 passed, zero skips, using a fresh owned PostgreSQL fixture; optional-driver-free focused validation:25 passed with the existing database integration test skipped until explicit opt-in.
