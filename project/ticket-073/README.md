# Ticket 073: Execution budget for reasoning-model routes

- **ID**: ticket-073
- **Owner**: human:founder
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-16

SESSION_EXECUTION_AUTHORIZATION: 2026-09-16, owner asked for the OpenRouter and z.ai
lanes to be made usable, with z.ai's own API serving the traffic it can. GitHub
allocation: issue #73.

## Goal and scope

`koru-agent/queue-executor` reports every candidate as `timeout` while the providers
answer in seconds. Measured on 2026-09-16 with the real 17 076-character agent prompt
from the koru queue (4191 input tokens), called directly with the lane's own key:

| call | time | result |
| --- | --- | --- |
| z.ai `glm-5.3`, `max_tokens=4096` | 4.86 s | `stop`, 108-char content |
| z.ai `glm-5.3`, no `max_tokens` | 8.92 s | `stop`, 103-char content |
| OpenRouter `z-ai/glm-5.3-flash`, `max_tokens=5` | 1.81 s | HTTP 200 |

`[execution]` allows `attempt_timeout_seconds = 12.0` and calls 10.0 s slow, so the
typical answer already counts as slow and ordinary variance — longer reasoning, a
larger context, the `python -m subllm.openai_worker` startup — crosses the cap. The
health store agrees: `zai fails=0 reason=slow_response`.

The caller budget is not the constraint. koru passes `timeout_seconds=1800.0` and
`client.py:463` clamps each attempt to `min(remaining, attempt_timeout_seconds)`.

Raise the per-attempt budget to 90.0 s and the slow threshold to 45.0 s, and move the
shipped-policy test with them. `[execution]` is operator configuration, so this
touches neither `VERSION`, `pyproject.toml` nor `src/`: `SUBLLM_SOURCE_DIGEST` stays
as consumers pinned it, and the mounted policy takes effect on a service restart
without an image rebuild.

Provider order is unchanged — `zai` priority 0 on its own API, `openrouter` priority
30 as the fallback — so z.ai carries the traffic when it answers and OpenRouter takes
over when it does not.

## Non-goals

- Any change under `src/`, including the missing `urlopen` timeout, the
  reasoning-only response classified as `invalid_response`, and the absent
  `max_tokens`. All three are real and recorded in issue #73 for their own ticket,
  because they change `SUBLLM_SOURCE_DIGEST` and force a pin migration in consumers.
- Disabling `cursor` despite 1528 consecutive `provider_unavailable` failures: it
  fails immediately rather than through a timeout, and its removal would change
  routing for every consumer.

## Acceptance criteria

- The shipped policy and `tests/test_policy_config.py` agree on 90.0 and 45.0.
- The full test suite passes.
- No pinned digest or consumer contract changes.
