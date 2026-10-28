# Ticket 159: Add local Ollama d1 System One routing to SubLLM

- **ID**: ticket-159
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-10-28

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user selected local Ollama `d1:3b` for
offline decision routing and requested that it be added to SubLLM for reuse by
Heyasa and other callers.

When the local Ollama installation includes `d1:3b`, route typed System One
requests to Ollama's native `/v1/systemone` endpoint. Prefer that exact tag;
do not treat other aliases as equivalent. Convert its
typed probabilities and answers to SubLLM's existing
`wellmanifest.system-one-response/v1` contract. Keep current Qwen chat and
governed SubLLM route fallbacks for missing models and transport failures.
Do not let model output change policy, authorization, or execution decisions.

Heyasa already calls SubLLM's typed decision endpoint, so it should reuse this
shared adapter without embedding a second model client. Flowguard may consume
the same endpoint for optional task classification; admission, leases, safety,
resource limits, and execution authority remain deterministic.

## Acceptance criteria

- [x] AC-01: SubLLM uses Ollama's native `/v1/systemone` API for the exact
  local `d1:3b` tag by default.
- [x] AC-02: d1 typed answers and probabilities normalize to the existing
  System One response schema; absent d1, malformed responses, and upstream
  failures retain the current Qwen and governed-route fallbacks.
- [x] AC-03: Proxy tests cover model selection, native request shape, response
  normalization, and fallback behavior.

## Validation

- `pytest -q tests/test_proxy.py`: rerunning after removing the unverified
  `d1-ultra` alias.
- The focused d1 tests cover native API request construction, typed answer
  conversion, missing-model selection, malformed-response rejection, and Qwen
  retry before the configured route fallback.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
