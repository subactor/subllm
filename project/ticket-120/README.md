# Ticket 120: Local Ollama development profiles with isolated OpenCode and bounded inference

- **ID**: ticket-120
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-08

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested autonomous local development, issue execution, checks, bug fixes and protected publication. Linked request: paxlet-com/willman PLF-113.

Provide an opt-in profile renderer usable as `python -m subllm.local_runtime`. Generate a SubLLM policy that disables built-in cloud and subscription providers, binds one exact local model to declared routes, and allows bounded inference time. Generate matching OpenCode configuration with one enabled provider and explicit tool capability/context. Never mutate the shared policy or global OpenCode configuration. LAN HTTP must use a loopback SSH tunnel under existing SubLLM policy.

Observed regression: `configured_routes(environ=...)` ignored the caller policy file when loading runtime policy. Include resolver and worker policy propagation fixes and an explicit-profile routing regression test; this is required for the generated isolated profile to be effective.

## Acceptance criteria

- [x] AC-01: Generated policy resolves only the selected local model for requested routes, with no credential or cloud fallback.
- [x] AC-02: Generated OpenCode configuration uses the same endpoint/model and explicit resource limits.
- [x] AC-03: Invalid endpoint, model, route and limits are rejected; existing output profiles are preserved.
- [x] AC-04: Offline regression tests and governance checks pass; actual minis SubLLM and OpenCode pilot results are retained externally.

## Validation

Run targeted profile/route tests and the managed governance gate. Validate live model routing and independently check the artifact from an isolated OpenCode tool-use pilot. Live checks do not prove fleet-wide issue delivery or authorize merge.

## Evidence

Full project suite: 622 passed, 2 dependency deprecation warnings, using the project virtual environment with MCP 1.28.1. Independent OpenCode pilots: Gemma4 12B and GPT-OSS 20B both passed the same 5 preserved assertions. Single-run tool-loop timings were 85.431s and 40.201s from the first emitted event, excluding CLI bootstrap; these are not a statistically sufficient model ranking. Live SubLLM caller-policy request returned MINIS_LOCAL_OK on Gemma4 in 6.60s. External receipt collection: `minis-autonomy-20261008` (host-state storage). Protected local CI/Validator publication remains required; this ticket stays IN_PROGRESS.
