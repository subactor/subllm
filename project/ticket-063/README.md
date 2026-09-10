# Ticket 063: Bounded code2dsl projection

Status: IN_PROGRESS
Workflow state: EDIT

SESSION_EXECUTION_AUTHORIZATION: implement and publish autonomy-execution R5/R8 under the existing user request. GitHub issue 63 allocates this legacy ticket. Preserve all canonical semantic records, validate before projection, bind full-record digests and retain compressed/expanded budgets. Reproduce the Core PLF-13887 extraction failure without spending another worker attempt before qualification.

Canonical result: https://github.com/subactor/docs/blob/main/architecture/analysis/autonomy-execution-receipt.md

Acceptance: `./scripts/verify` (284 tests, lint, build); five real-runtime integration tests. Frozen Core e0dbd082 extraction preserves 67,271 records from 1,461 files in 7,279,456 compressed / 66,484,514 expanded bytes. Frozen PLF-13849 preserves 32,271 records from 785 files in 3,613,232 / 30,253,356 bytes with extractor cdf29f2c19a0edbab65f76269240502de04c568d. Limits remain 16 MiB compressed and 64 MiB expanded. Core has limited remaining capacity; larger projections still fail closed.
