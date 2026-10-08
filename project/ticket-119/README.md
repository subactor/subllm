# Ticket 119: Prompt MCP stdio upstream failure propagation

- **ID**: ticket-119
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application
- Workspace request: PLF-2991, parent PLF-054

## Goal and scope

The configured Unix bridge waited 45 seconds after an authenticated HTTP403 because
SDK stdio input used a blocking readline thread. Make stdin cancelable on native
Unix pipes and propagate bounded closed error categories without exposing data.
Preserve valid message forwarding, TLS/auth checks and existing non-Unix fallback.

## Acceptance criteria

- Positive initialize/tools/list, error forwarding and EOF behavior remain valid.
- Denial, unavailable and malformed transport exit promptly while stdin stays open.
- No raw error bodies, tokens or credential locators reach CLI diagnostics.
- Required source/governance checks and exact-head independent OneDev/Validator precede
  merged-only client runtime deployment and actual 25 route and denial readback.

## Boundaries

No gateway policy, credentials, providers, Platform, broker or shared service restart.
Session authorization is the user's repeated continue, repair, test and merge request.

## Execution binding

SESSION_EXECUTION_AUTHORIZATION:user/continue-repair-test-merge-deploy
Maximum active session: 120 minutes. Schema normalization preserves scope and criteria.

## Validation

- Original CLI: 6 timeouts and 1 successful handshake in 32.03 s.
- Targeted SDK 1.28.1 regressions pass, including failure and EOF cleanup.
- Production SDK 1.26.0 compatibility: 8/8 real subprocess cases pass, including large UTF-8 messages and JSON-RPC errors.
- Full scripts/verify: source lint, docs/logs contracts, bytecode, tests and package build pass.
- Managed governance passes; independent exact-head publication remains required.
