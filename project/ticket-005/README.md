# Ticket 005: Add zero-dependency OpenAI-compatible SubLLM client

- Status: IN_PROGRESS
- Workflow state: PUBLICATION
- Workstream: application
- Owner: agent:codex under SESSION_EXECUTION_AUTHORIZATION

## Goal

Expose one lightweight execution API for policy-resolved routes so consumers
do not duplicate provider URLs, model defaults, credentials or LiteLLM setup.

## Acceptance criteria

- [x] `complete()` resolves provider and model through SubLLM policy.
- [x] Direct Z.AI requests use the fixed API base, `glm-5.3` wire model and
  application attribution fields.
- [x] Errors and returned metadata never expose the credential value.
- [x] The full SubLLM verification suite passes.
