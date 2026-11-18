---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "proxy-access-control",
  "kind": "information",
  "version": 1,
  "title": "Local proxy browser access control",
  "status": "implemented",
  "owner": "subactor/subllm",
  "created": "2026-11-18",
  "updated": "2026-11-18",
  "review_after": "2026-12-18",
  "source_revision": "d4fa58cef82ae86bbd5c7d094ced7796bc7763ea",
  "scope": "repository",
  "affected_repositories": [
    "subactor/subllm"
  ],
  "evidence": [
    "repo://subactor/subllm/tests/test_proxy.py",
    "https://github.com/subactor/subllm/pull/233"
  ]
}
---

# Local proxy browser access control

<!-- docs:section purpose -->
## Purpose

`subllm proxy` (default `127.0.0.1:11435`) is reachable from any page open in
the operator's browser, because the browser sends the loopback `Host` itself.
This document describes how the proxy limits browser access and how routed,
possibly paid, completions can additionally require a bearer token.

<!-- docs:section scope -->
## Scope

The Ollama-compatible and OpenAI-compatible proxy in `src/subllm/proxy.py`.
The authenticated gateway (`subllm-gateway`) is described in
[Unified LLM and MCP proxy](unified-proxy.md) and is not affected.

<!-- docs:section evidence -->
## Evidence

- `tests/test_proxy.py`: foreign origins are rejected for preflight, `GET` and
  `POST` without a provider or upstream attempt; listed origins are echoed;
  routed models require the configured bearer token, also for streaming; the
  local Ollama forward stays open.
- subactor/subllm#233 (ticket-222, repair plan SUB-01).

<!-- docs:section content -->
## Content

| Variable | Default | Effect |
| --- | --- | --- |
| `SUBLLM_PROXY_ALLOWED_ORIGINS` | empty | Comma-separated extra browser origins, for example `https://ui.example.org`. Loopback page origins (`http(s)://127.0.0.1`, `localhost`, `[::1]` on any port) are always allowed. |
| `SUBLLM_PROXY_TOKEN` | unset | When set, routed completions (policy routes that may reach paid or cloud providers) require `Authorization: Bearer <value>`. |

- A request whose `Origin` is not allowed receives `403 PROXY-ORIGIN`, for both
  the preflight and a simple request, before any provider attempt or raw Ollama
  forward. No CORS headers are sent to it.
- An allowed origin is echoed in `Access-Control-Allow-Origin` with
  `Vary: Origin`; the proxy never answers `*`.
- Requests without an `Origin` header (CLI, `curl`, local agents) are unchanged.
- With `SUBLLM_PROXY_TOKEN`, a missing or wrong bearer token on a routed model
  returns `401 PROXY-AUTH` and never falls back to the raw upstream; the direct
  forward of unregistered models to local Ollama stays available.
- Keep the token value in the private credential store, never in tracked files.

<!-- docs:section limitations -->
## Limitations

Loopback origins stay allowed so local web UIs such as willmux can use the
proxy; another local service that serves attacker-controlled pages on loopback
is therefore trusted. The token protects routed models only, not the local
Ollama forward.

<!-- docs:section next_actions -->
## Next actions

- Describe the variables in the README quick start (governance workstream).
- Consider requiring the token for all non-loopback-origin requests once
  browser clients send it.
