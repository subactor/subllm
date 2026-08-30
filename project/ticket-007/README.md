# Ticket 007: Enforce wall-clock OpenAI-compatible attempt deadlines

- Status: IN_PROGRESS
- Workflow state: PUBLICATION
- Workstream: runtime
- Owner: agent:codex under SESSION_EXECUTION_AUTHORIZATION
- Tracking issue: https://github.com/subactor/subllm/issues/34

## Goal

Make the configured attempt timeout a total wall-clock deadline for
OpenAI-compatible providers instead of a per-socket-operation timeout, so a
slow streaming response cannot consume the complete Supervisor budget and
prevent policy failover.

## Acceptance criteria

- [x] Each HTTP attempt runs in a fixed worker and a new process session.
- [x] Timeout terminates the complete worker process group; no descendant
      remains executing even on minimal containers that retain zombie PIDs.
- [x] Worker input validates the provider base, wire model, credential shape,
      attribution fields and protected headers against SubLLM policy.
- [x] The credential travels through stdin and is absent from argv and receipts.
- [x] Retryable HTTP/transport outcomes continue bounded failover.
- [x] A real-process regression proves a hanging descendant stops executing.
- [x] Full verification passes; protected publication is pending.
- [ ] Live Supervisor readback completes within its total budget without
      residual attempt workers.
