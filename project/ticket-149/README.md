# Ticket 149: Serve System One decision requests in subllm-proxy with local Ollama Qwen3.5 fallback

- **ID**: ticket-149
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-26

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested enabling `SYSTEM_ONE_ENDPOINT`
decisions through `subllm-proxy` using local Ollama models (`qwen3.5:0.8b` /
`qwen3.5:4b`) with governed SubLLM route fallback.

This ticket adds native `POST /v1/decide` and `POST /v1/system-one/decide`
handlers to `SubLLMProxyHandler` in `src/subllm/proxy.py` accepting
`wellmanifest.system-one-request/v1` payloads (`choice`, `score`, `noul`
questions), dispatching first to local Ollama (`qwen3.5:0.8b` / `qwen3.5:2b` /
`qwen3.5:4b` with `think=False` and `format="json"`) when available on the
configured or default local Ollama daemon (`http://127.0.0.1:11434`), falling
back to governed SubLLM routes (`heyasa/command`), and returning normalized
`wellmanifest.system-one-response/v1` probability distributions and answers.

## Acceptance criteria

- [x] AC-01: `POST /v1/decide` and `POST /v1/system-one/decide` in
  `src/subllm/proxy.py` accept `wellmanifest.system-one-request/v1` requests and
  return `wellmanifest.system-one-response/v1` with normalized `probabilities`
  and `answers`.
- [x] AC-02: Local Ollama Qwen3.5 models (`qwen3.5:0.8b`, `qwen3.5:2b`,
  `qwen3.5:4b`) are selected automatically when local Ollama is reachable, with
  automatic fallback to SubLLM route execution when local Ollama is unavailable.
- [x] AC-03: Proxy unit tests and repository governance checks pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
