# Ticket 081: Ollama and OpenAI-compatible proxy server with ticket attribution and local daemon forwarding

- **Status**: DONE
- **Workflow state**: PUBLICATION
- Workstream: runtime
- Owner: agent:antigravity under SESSION_EXECUTION_AUTHORIZATION

## Goal

Provide a zero-credential, password-free Ollama- and OpenAI-compatible proxy server
running locally within Subactor SubLLM (`subllm proxy`) so that tools and agents
(`koru`, `tillm`, `gillm`, `taskand`, `premesh`, Cursor, Aider, IDEs) can transparently
access paid and local LLMs (Z.AI GLM-5.3, Gemini, OpenAI Codex, Claude, Ollama)
without requiring client-side API keys, with full ticket attribution and local Ollama daemon fallback.

## Acceptance criteria

- [x] Standard OpenAI-compatible routes: `GET /v1/models`, `POST /v1/chat/completions` (JSON and SSE streaming).
- [x] Standard Ollama-compatible routes: `GET /api/tags`, `GET /api/version`, `POST /api/chat`, `POST /api/generate`, `POST /api/show` (JSON and NDJSON streaming).
- [x] Password-free local bind with CORS headers for browser frontends (like Premesh UI).
- [x] Dynamic model resolution for SubLLM catalog models, route aliases (`koru-agent/queue-executor`), and fallback to local Ollama daemon on `127.0.0.1:11434`.
- [x] Ticket attribution through HTTP headers (`X-Ticket`, `X-Subactor-Ticket`) and model suffix (`model@ticket-NNN`), persisting execution receipts in `~/.subactor/receipts`.
- [x] Integrated CLI: `subllm proxy [--host 127.0.0.1] [--port 11435] [--ollama-upstream http://127.0.0.1:11434]`.
- [x] 100% unit test verification with 345 passing tests and clean ruff check.
