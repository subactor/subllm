# Ticket 176: Point the minis custom provider at the existing minis Ollama tunnel port

- **ID**: ticket-176
- **Owner**: agent:devin
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-29

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested cloud-first routing with local
fallback through minis (ticket-175) and asked to continue and merge.

ticket-175 pointed `[custom_providers.minis]` at `127.0.0.1:11436`, which on the
proxy host is a SubLLM proxy listener (`serve_proxy(port=11436)`), not Ollama.
The persistent tunnel to minis (`minis-ollama-tunnel.service`) forwards
`127.0.0.1:11439` to Ollama on minis, where `qwen3:8b` is installed and
pinned on the GPU. Only the port and its comment change.

## Acceptance criteria

- [x] AC-01: minis api_base is `http://127.0.0.1:11439/v1`, the port served by minis-ollama-tunnel.service.
- [x] AC-02: `qwen3:8b` answers `/v1/chat/completions` through that port on the proxy host.
