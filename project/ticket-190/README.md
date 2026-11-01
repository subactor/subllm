# Ticket 190: Return bounded MCP failure when gateway audit policy is invalid

- **ID**: ticket-190
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-01

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested repair and protected publication of MCP errors. Policy validation failed during pre-dispatch audit and the client hung. Return an explicit sanitized bounded error while preserving fail-closed policy, complete auditing, and no duplicate side effects.

## Acceptance criteria

- [x] AC-01: Failed audit on initialize or later request returns a sanitized bounded error and does not dispatch upstream work.
- [x] AC-02: Normal MCP interactions and existing error/side-effect handling remain correct.
- [ ] AC-03: Run focused tests and governance, then seek independent protected publication.
