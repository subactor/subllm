# Ticket 108: Centralized timeout hierarchy and usage timeout display

- **ID**: ticket-108
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
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
