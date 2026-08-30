# Ticket 005: Add zero-dependency OpenAI-compatible SubLLM client

- Status: IN_PROGRESS
- Workflow state: PUBLICATION
- Workstream: application
- Owner: agent:codex under SESSION_EXECUTION_AUTHORIZATION

## Goal

Expose one lightweight execution API for policy-resolved routes so consumers
do not duplicate provider URLs, model defaults, credentials or LiteLLM setup.

The bounded follow-up exposes that same API as the closed `subllm-complete`
stdin-JSON adapter. Runtime consumers can therefore use SubLLM-owned transport
and failover, including Cursor SDK, without receiving credentials or a generic
execution surface. Tracking issue: https://github.com/subactor/subllm/issues/29

## Acceptance criteria

- [x] `complete()` resolves provider and model through SubLLM policy.
- [x] Direct Z.AI requests use the fixed API base, `glm-5.3` wire model and
  application attribution fields.
- [x] Errors and returned metadata never expose the credential value.
- [x] The full SubLLM verification suite passes.
- [x] A bounded CLI accepts only the declared completion request fields and
      emits a secret-free provider/model/attempt receipt.
- [x] The local verification gate cannot skip Python files merely because its
      worktree is nested below a gitignored workspace directory.
