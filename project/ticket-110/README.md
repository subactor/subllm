# Ticket 110: Honor configured timeout in OpenAI proxy requests

- **ID**: ticket-110
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continue repair and live testing of the
Cursor Auto API and Validator. The proxy caps requests at a hardcoded 60 seconds
although SubLLM execution policy exposes a configurable attempt budget.
Use the configured budget when timeout is omitted; preserve explicit positive
finite request timeouts and reject invalid ones before provider execution.

## Acceptance criteria

- [x] Configured default reaches completion dispatch.
- [x] Explicit request limits retain precedence; invalid limits return 400.
- [ ] Focused tests, governance and protected publication pass.

41 focused proxy and Cursor tests passed.
