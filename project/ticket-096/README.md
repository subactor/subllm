# Ticket 096: Persist gateway session and unify LLM/MCP interaction history

- **ID**: ticket-096
- **Owner**: codex / api-telemetry-20260919
- **Workstream**: application
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT

## Goal and scope

Keep the gateway credential across a full refresh for the current browser session and expose gateway archives together with metadata-only LLM transport telemetry in one authenticated interaction view. Preserve the distinction between captured request/response bodies and metadata-only records.

## Acceptance criteria

- [ ] Session refresh restores the token from session storage and logout removes it.
- [ ] The interaction endpoint merges authorized MCP, gateway LLM, and legacy LLM telemetry records.
- [ ] Metadata-only rows clearly state that request and response bodies were not captured.
- [ ] Tests cover merged list/detail projections and preserve credential isolation.

SESSION_EXECUTION_AUTHORIZATION: user requested continuation, testing, publication and merge. No provider policy, credential value or authority changes.
