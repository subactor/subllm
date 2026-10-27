# Ticket 151: Qualify SQLite writer admission without host speed assumptions

- **ID**: ticket-151
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-27

SESSION_EXECUTION_AUTHORIZATION: the user requested execution of the outstanding subactor/subllm issues on 2026-10-27, including implementation, testing and protected publication. This isolated ticket addresses issue #153 only.

## Goal and scope

Qualify the SQLite writer regression in tests/test_usage_indexes.py. Separate real persistence from deterministic same-inode sharing, FIFO admission and deadline fault injection. Production code, its five-second budget and supported multiprocessing start methods remain unchanged.

## Acceptance criteria

- [x] AC-01: Distinct stores and hard-linked paths share one inode gate while unrelated inodes remain independent; persisted records and event sequences are complete.
- [x] AC-02: Controlled scheduling proves busy exclusion and FIFO; injected queue timeout cleans its marker and permits later admission.
- [x] AC-03: Controlled elapsed time proves the original five-second budget is shared with SQLite and cannot become negative; all multiprocessing start methods remain covered.
- [ ] AC-04: Focused checks, intentional broken-gate mutation, stack checks and governance pass; request independent exact-head publication.

Validation on 2026-10-27: focused storage suite 85 passed, including fork/spawn/forkserver on this host. Full scripts/verify passed: 933 tests, Ruff, compilation, documentation/report and logs checks, wheel and sdist builds. The full run used the dedicated usage_test_ticket151 PostgreSQL container and took 66.89 seconds; no production storage or paid provider was used. Governance and git diff --check pass.

Three in-memory negative controls each fail the intended regression: a registry that never shares a gate, an admission predicate that ignores FIFO, and a six-second admission budget. These mutations do not alter repository source. Safe receipts and raw logs remain outside Git in the host session receipt directory subllm-backlog-20261027 (mutations.json and verify-final-result.json).

Protected publication uses the configured onedev/local-verify profile and independent Validator for the exact PR head and current base. Passing local checks does not approve the merge.
