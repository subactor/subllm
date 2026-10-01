# Ticket 109: Cursor CLI transport for locally authenticated review

- **ID**: ticket-109
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-01

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the operator requested continued repair, testing
and protected publication using Cursor, with minimum quality GLM-5.3-Flash.
The local login works with Auto while Cloud Agent SDK requires a paid plan.
Add a separate, explicitly opted-in Cursor CLI transport with bounded execution,
no inherited API credentials, private workspace and denied agent tools.
Auto is a routing mode, not a qualified model or a guarantee of cost or quality.
Keep it disabled by default; do not change deployed protected review policy.

## Acceptance criteria

- [x] CLI login executes without Cursor SDK or API credentials.
- [x] Reject malformed/error output, bound prompts/output/time, restrict tools.
- [x] Policy preserves SDK routes and defaults the CLI provider to disabled.
- [ ] Tests and governance pass; publish through independent controller.

## Validation

228 focused tests passed, including transport failures, policy compatibility,
resolver and completion dispatch. Live Cursor CLI Auto returned {"ok": true}
through the new adapter using only local login. No deployed routing changed.
