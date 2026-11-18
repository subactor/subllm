# Ticket 239: Reject non-object POST JSON payloads and forward hf.co local Ollama tags in proxy

- **ID**: ticket-239
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION
- **Created**: 2026-11-18

## Goal and scope

Close `LLM-005` and `LLM-010` in `src/subllm/proxy.py` and verify via `tests/test_proxy.py`:
- Reject non-object JSON payloads (`list`, `int`, `str`, `bool`) on non-speech `POST` routes with HTTP `400` (`INVALID_REQUEST`) before handler dispatch (`_schema_gate_rejects` / `_handle_*`).
- Allow unmanaged local Ollama `hf.co/<org>/<repo>:<tag>` GGUF models (without `..`) to fast-forward and pass Ollama options directly to upstream Ollama, while keeping unknown `app/fn` routes failing closed.

## Acceptance criteria

- [ ] AC-01: Non-object JSON bodies on `POST /api/chat`, `/v1/chat/completions`, `/v1/decide`, and `/api/embeddings` return HTTP `400` with `INVALID_REQUEST`.
- [ ] AC-02: `hf.co/...` local Ollama tags forward directly to upstream Ollama including `options` (such as `num_ctx`), while unknown `app/fn` route strings still fail closed.
- [ ] AC-03: `ruff`, `C901 <= 15`, targeted `pytest`, and governance gates pass cleanly.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
