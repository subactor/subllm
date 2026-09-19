# Ticket 077: DeepSeek fallback on koru-agent routes

- **ID**: ticket-077
- **Owner**: human:founder
- **Status**: DONE
- **Workflow state**: PUBLICATION
- **Created**: 2026-09-17

SESSION_EXECUTION_AUTHORIZATION: 2026-09-17, owner asked to fix koru autonomy so
the queue can run on DeepSeek when the other lanes are unavailable. GitHub
allocation: issue #77.

## Goal and scope

`koru-agent/queue-executor` (and the other koru-agent routes) had a bounded
candidate list of `zai/glm-5.3 -> cursor/gpt-5.6-sol -> cursor/grok-4.6 ->
openrouter/<default>`. On 2026-09-17 all three lanes failed in the same window
(zai HTTP 429, cursor provider_unavailable — see issue #76, OpenRouter GLM
timeout), and koru's `max_attempts=1` closed the tickets as failed.

`deepseek-v4-pro` is already catalogued in `MODELS` on the OpenRouter lane.
This ticket appends it as a strictly-later candidate (priority_offset 30) on
every `koru-agent/*` route via a `_KORU` list derived from `_DEFAULT`. Other
applications keep the shared list unchanged.

## Acceptance criteria

- [x] AC-01: every koru-agent route ends with `openrouter/deepseek-v4-pro`
      after the shared fallbacks (regression test).
- [x] AC-02: non-koru routes do not gain the deepseek candidate (regression
      test).
- [x] AC-03: `./scripts/verify` passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
