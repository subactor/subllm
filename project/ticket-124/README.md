# Ticket 124: Fix MCP upstream rejection model validation in gateway

- **ID**: ticket-124
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-10-15

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested inspecting and repairing issues across subactor repositories.
1. Fix MCP upstream rejection model validation in `src/subllm/gateway_mcp.py` to use `JSONRPCError.model_validate` fallback when `JSONRPCMessage` is a UnionType.

## Acceptance criteria

- [x] AC-01: `src/subllm/gateway_mcp.py` safely validates JSON-RPC error responses across MCP SDK versions.
- [x] AC-02: Governance check `./project/governance-check.sh` passes cleanly with 0 errors.
- [x] AC-03: Gateway test suite passes cleanly.

## Validation

- Governance: `./project/governance-check.sh` reports `GOV-PASS: passed (0 errors, 0 warnings)`.
- Tests: `pytest tests/test_gateway.py tests/test_gateway_history.py tests/test_gateway_mcp_http.py` passes cleanly.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
