# Ticket 187: Support bounded reasoning controls for local coding models

- **ID**: ticket-187
- **Owner**: agent:codex (session `2026-10-31-qwen-smaller-model-canary`)
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-31

## Goal and scope

Allow an explicitly configured custom OpenAI-compatible provider to set a
bounded `reasoning_effort` request parameter, including `none`. This lets the
Minis Qwen3.5 9B coding canary disable hidden reasoning, which was the cause of
slow or empty completions. The parameter remains opt-in and is sent only on
routes for that custom provider. Missing configuration preserves existing
requests.

`SESSION_EXECUTION_AUTHORIZATION`: the user asked to use a smaller-than-27B
model on Minis and benchmark its speed, and has repeatedly authorized autonomous
configuration, testing, merging and local deployment for this coding setup.
This ticket implements the bounded SubLLM support required to evaluate and use
that model. It does not change Validator routing.

Implementation paths are limited to `src/subllm/policy_config.py`,
`src/subllm/resolver.py`, `tests/test_policy_config.py` and
`tests/test_custom_providers.py`.

## Acceptance criteria

- [x] AC-01: Custom-provider policy accepts only the bounded `reasoning_effort`
  values `low`, `medium`, `high` and `none`; invalid values and fields fail closed.
- [x] AC-02: The resolver carries configured parameters only to that custom
  provider's declared routes; existing providers and unset configuration are
  unchanged.
- [x] AC-03: Unit tests verify parsing, validation and request parameter
  propagation.
- [x] AC-04: The Minis Qwen3.5 9B `onedev-agent/code-edit` canary passes a real
  Python syntax and behavior check through SubLLM, with latency recorded against
  Qwen3.8 27B and Qwen2.5-Coder 14B.
- [ ] AC-05: The managed governance gate, relevant test suite, protected exact-head
  verification and independent Validator publication pass.

## Tracking boundary

Only the coding route is eligible for this model canary. Other application
routes, especially `validator-agent`, remain on their independently configured
providers and models.

## Verification evidence

- `testless scan -s src/subllm` over `tests/test_custom_providers.py` and
  `tests/test_policy_config.py`: 40 passed in 3.37 s; governance preflight had
  0 errors and 0 warnings.
- `./project/governance-check.sh`: passed, 0 errors and 0 warnings.
- Live SubLLM call to Minis `qwen3.5:9b`, using the bounded
  `reasoning_effort = "none"` setting: first call 13.219 s, warm repeat 3.864 s.
  Both generated Python snippets parsed and passed all three behavior checks.
- Benchmark evidence is retained in the host-local canary state at
  `~/.local/state/subllm/two-host-coding-canary-20261028/subllm-qwen35-9b-codegen-20261031.json`.
- The same small prompt through SubLLM with Qwen2.5-Coder 14B took 47.079 s
  first call and 6.778 s warm; generated code passed the same checks. Earlier
  direct Qwen3.8 27B requests took 37.48 s at 2.9k input tokens and timed out
  at 150.1 s with 8k input tokens. These prompts differ in size, so the 27B
  measurements are reference points, not a matched speedup claim.
- AC-05 remains open until protected exact-head OneDev verification and the
  independent Validator publication pass.
