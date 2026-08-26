# Ticket 010: Register semcod/prellm routes

- Status: IN_PROGRESS
- Workflow state: IMPLEMENTATION
- Workstream: routing
- Owner: agent:codex under SESSION_EXECUTION_AUTHORIZATION

## Goal

Register the public `semcod/prellm` consumer in the central SubLLM policy so
both preprocessing and execution calls resolve to direct Z.AI `glm-5.3` by
default without embedding provider policy in PreLLM.

## Acceptance criteria

- [x] `prellm/preprocess` and `prellm/execute` are exact registered routes.
- [x] Both routes prefer direct Z.AI `glm-5.3` deterministically.
- [x] Application attribution points to `https://github.com/semcod/prellm`.
- [x] The full SubLLM verification suite passes.
