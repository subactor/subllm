# Ticket 175: Prefer available cloud providers, then local Ollama on minis and the proxy host

- **ID**: ticket-175
- **Owner**: agent:devin
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-29

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested that SubLLM uses whatever the
environment offers: available cloud providers first, local models only when no
provider is available, including the LAN host minis (16 GB Ollama).

The shared `subllm.toml` orders every credentialed cloud provider (including
OpenRouter) before local inference, adds `[custom_providers.minis]` reached
through a loopback SSH tunnel (command documented in `subllm.toml`) and keeps the
proxy host's Ollama as the final candidate.

## Acceptance criteria

- [x] AC-01: On every route that already declares ollama, cloud candidates precede minis, and minis precedes the proxy-host ollama.
- [x] AC-02: minis covers exactly the routes whose built-in chain includes ollama and requires the same `OLLAMA_API_KEY` credential.
- [x] AC-03: LAN HTTP is not accepted; minis uses a loopback tunnel.
