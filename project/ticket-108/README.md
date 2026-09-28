# Ticket 108: Centralized timeout hierarchy and usage timeout display

- **ID**: ticket-108
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-09-28

## Goal and scope

1. Implement centralized hierarchical timeout resolution in SubLLM policy configuration and environment loading (per-model, per-provider, and global default timeout).
2. Support model and provider timeout lookups across gateway client routes, proxy execution, and interaction context.
3. Enhance web usage panel (`usage.html`, `usage.js`) to display timeout limits, color-coded latency, and request durations.
4. Ensure all unit tests pass and repository governance check succeeds.

## Acceptance criteria

- [x] AC-01: Centralized hierarchical timeout resolution in `policy_config.py` and `credential_env.py` (resolving per-model, per-provider, then default timeout).
- [x] AC-02: SubLLM proxy, client routes, and interaction context record effective timeout limit on attempts.
- [x] AC-03: Web usage panel displays `timeout_limit_seconds` column and highlights slow/timeout-prone requests.
- [x] AC-04: Full test coverage in `test_policy_config.py` and `test_credential_env.py`.
- [x] AC-05: Test suite and `./project/governance-check.sh` pass.

## Session authorization

User explicit request "kolejno" authorizing execution of proposed improvements (including centralized timeout settings and usage panel display) treated as SESSION_EXECUTION_AUTHORIZATION.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

## Explicit handoff and continuation

The user confirmed that agent agy finished and handed this scope to Codex for
publication and deployment. The prior expired claim was terminally released,
then a bounded replacement was acquired with monotonic fencing. Source and
commits are preserved. Initial read-only policy/environment tests: 35 passed.
Review found caller-deadline expansion, silent fallback for invalid overrides,
and omitted dynamic timeout values during credential-file import. These must
pass focused regressions before publication.

- [ ] AC-06: Independent protected publication and approved runtime activation.

## Validation and final behavior

525 full-suite tests pass. Eleven focused deadline regressions initially showed
10 failures; all pass after correction. Explicit and default caller budgets are
never enlarged; failover shares one deadline. Invalid overrides fail closed,
and dynamic timeout settings survive private-file import. Archive records keep
the exact effective attempt budget. Panel columns and latency boundaries are
checked with Node vectors and syntax validation. Ruff and governance pass, and
wheel/sdist build successfully. Ten pre-existing lint findings in the archive,
usage reader and PostgreSQL tests were corrected without behavior changes to
satisfy the configured OneDev gate. Source defaults stay at 12/10 seconds;
existing deployed environment overrides remain authoritative.

AC-06 remains pending independent publication and approved runtime activation.
