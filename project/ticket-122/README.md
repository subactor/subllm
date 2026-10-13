# Ticket 122: Use ticket-096 to persist the gateway token for the current browser session and expose one authenticated interaction history for MCP, gateway LLM, and metadata-only direct LLM attempts.

- **ID**: ticket-122
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-13

## Goal and scope

Persist gateway session token for the current browser session (session-scoped authentication without token exposure in URLs or logs) and expose unified authenticated interaction history for MCP and LLM attempts.

## Acceptance criteria

- [x] AC-01: Gateway token persists for current browser session across page reloads (using sessionStorage or secure cookie), clearing on logout.
- [x] AC-02: Expose unified interaction history endpoint returning normalized entries for both MCP tools and LLM completions.
- [x] AC-03: Calls outside gateway retain metadata-only telemetry labeling with secret safety preserved.
- [x] AC-04: Test coverage for session persistence, reload, logout, caller isolation, and MCP/LLM interaction row details.

## Evidence

Targeted gateway tests: 39 passed in 15.01s. Governance check: passed (0 errors, 0 warnings).

SESSION_EXECUTION_AUTHORIZATION: User authorized autonomous task execution across ~/github/*/*.
