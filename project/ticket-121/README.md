# Ticket 121: OpenAI-compatible client timeouts reasoning responses and max tokens

- **ID**: ticket-121
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-13

## Goal and scope

Fix three defects in OpenAI-compatible client execution (`src/subllm/openai_worker.py` and `src/subllm/client_workers.py`):
1. **HTTP timeout in `urlopen`**: Pass `timeout_seconds` down to `openai_worker` and apply it directly in `urlopen(request, timeout=...)` so the worker reports socket/read timeouts gracefully before the parent process group is killed via SIGKILL.
2. **Reasoning model response handling**: When `choice["message"]["content"]` is empty or null, but `reasoning_content` (e.g. z.ai) or `reasoning` (e.g. OpenRouter) is present and `finish_reason == "length"`, return a distinct `truncated` result (or proper handling) with reasoning details rather than a misleading `invalid_response`.
3. **Route `max_tokens` support**: Ensure `max_tokens` from model parameters/request fields is passed through to the request payload if configured.

## Acceptance criteria

- [x] AC-01: `openai_worker` receives `timeout_seconds` and uses it as the `timeout` parameter in `urlopen`.
- [x] AC-02: Socket / HTTP timeouts during `urlopen` report `timeout` outcome directly from the worker.
- [x] AC-03: Empty `content` with present `reasoning` / `reasoning_content` when `finish_reason == "length"` returns a distinguishable outcome (`truncated` with reasoning token message) instead of `invalid_response`.
- [x] AC-04: `max_tokens` is preserved in the request payload.
- [x] AC-05: Unit and integration tests in `tests/test_openai_worker.py` and `tests/test_client.py` verify the behavior.

## Validation

Run targeted client/worker tests and full pytest suite under virtual environment. Run `./project/governance-check.sh`.

## Evidence

Targeted tests: 43 passed. Full project suite: 627 passed, 2 deprecation warnings in 66.83s. Governance checks passed (0 errors, 0 warnings).

SESSION_EXECUTION_AUTHORIZATION: User requested execution of backlog tasks for subllm (#75). No secret access or external API modifications.
