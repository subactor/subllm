# Ticket164: Pin patched MCP session lifecycle dependency

- **ID**: ticket-164
- **Owner**: agent:codex / codex-mcp-patch-20261028
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-28

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continued user-authorized SubLLM backlog maintenance, tests and protected publication. Resolve the dependency version affected by GHSA-84m7-p3x7-pcfv / repository Dependabot alert5 using upstream MCP1.30.0. Existing gateway cap16 bounds retained sessions; upstream patch adds proper reclamation. Current metadata uses1.28.1 in both optional gateway/test extras.

## Acceptance criteria

- [x] AC-01: Both extras require exact patched1.30.0, preserving base/development dependency contracts.
- [ ] AC-02: Actual patched SDK gateway integration and required current-base CI pass; independent Validator publishes exact head. No running service upgrade or index publication is inferred.

## Tracking boundary

Keep IN_PROGRESS / PUBLICATION through review and merge. Protected external receipt owns completion. Prior47gateway cases already pass in an isolated1.30.0 qualification; revalidate in this owned checkout before publication.

## Validation

Actual installed MCP1.30.0 passes all47gateway tests under Testless in this owned checkout. Dependency check and native governance pass. Both optional dependency declarations use the patched exact version. Existing gateway session cap remains in source. Full current-head hosted matrix and protected OneDev are pending; no shared service restart or live dependency upgrade occurred.
