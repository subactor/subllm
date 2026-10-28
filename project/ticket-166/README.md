# Ticket 166: Use OpenAI-compatible LiteLLM bindings for Ollama v1 endpoints

- **ID**: ticket-166
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-28

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested "kontynuuj, testuj, scalaj, wykonuj zalegle". Repair the Ollama LiteLLM protocol mismatch observed under GitHub issue #172. The provider already declares an OpenAI-compatible /v1 endpoint, but its model bindings select LiteLLM's native Ollama API and return 404. Preserve the provider, model and wire identities, operator configuration, credentials and routing priority; select the matching OpenAI adapter. No runtime activation or model qualification is inferred from source tests. The separately observed local 30B tag identifying a 3.1B model remains an owner recovery dependency.

## Acceptance criteria

- [x] AC-01: Every built-in Ollama model uses the declared OpenAI-compatible protocol, preserving its wire model and provider attribution.
- [x] AC-02: A real LiteLLM request reaches a loopback OpenAI /v1/chat/completions endpoint; native-endpoint mismatch is reproduced before the fix.
- [ ] AC-03: Existing policy and routing regressions and governance pass; the exact head is independently verified and published.

## Verification

Before the source change, six regression cases failed, including a real LiteLLM request to the wrong `/v1/api/generate` path returning HTTP 404. Afterward, all 148 focused policy, resolver, routing-contract and consumer tests pass. Nine affected coverage cases and managed governance pass. Testless proposals remain private advisory evidence. The consumer test uses LiteLLM 1.99.0 and a synthetic loopback server; it does not qualify any deployed model or restore a provider account's budget. Exact-head protected publication remains pending.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
