# Ticket 006: Bound Cursor SDK completion process trees

- Status: IN_PROGRESS
- Workflow state: PUBLICATION
- Workstream: runtime
- Owner: agent:codex under SESSION_EXECUTION_AUTHORIZATION
- Tracking issue: https://github.com/subactor/subllm/issues/32

## Goal

Keep the SubLLM completion deadline authoritative when Cursor SDK blocks while
closing its agent context, and prevent its shell/Node bridge descendants from
surviving a timed-out attempt.

## Acceptance criteria

- [x] Cursor execution uses a fixed, closed stdin/stdout worker protocol.
- [x] The API key is passed through stdin and never appears in argv or receipts.
- [x] Each worker owns a new process session and timeout reaps the entire group.
- [x] A failed Cursor attempt remains retryable so SubLLM can continue failover.
- [x] A real-process regression proves a hanging descendant is terminated.
- [x] Full SubLLM verification passes; protected publication is pending.
- [ ] Live Supervisor readback completes without leaked Cursor bridge processes.
