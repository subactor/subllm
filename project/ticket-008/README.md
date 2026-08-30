# Ticket 008: Allow bounded runtime tuning of attempt deadlines

- Status: DONE
- Workflow state: DONE
- Workstream: runtime
- Owner: agent:codex under SESSION_EXECUTION_AUTHORIZATION
- Tracking issue: https://github.com/subactor/subllm/issues/36

## Goal

Let an operator tune the per-provider attempt deadline independently of the
immutable provider/application catalog while preserving sequential failover and
the caller's total completion budget.

## Acceptance criteria

- [x] `SUBLLM_ATTEMPT_TIMEOUT_SECONDS` overrides only the per-attempt deadline.
- [x] `SUBLLM_SLOW_RESPONSE_SECONDS` overrides only the health threshold.
- [x] Both values remain bounded from 0.1 to 3600 seconds.
- [x] A slow-response threshold above the attempt deadline fails closed.
- [x] Provider membership, priority, models and the maximum attempt count remain
      owned by the validated policy catalog.
- [x] Full verification passes with 203 tests and protected PR #37 merged exact
      head `6fee19d4c6914f8d42c5ac2793086847a71cce68` as
      `3d77edd38d9d042b6e604d40df565c76f75a554c`.
- [x] Immutable live Supervisor readback completed three assessments through
      Cursor after a bounded 30-second ZAI attempt; health remained ready and
      idle process readback found no attempt workers or bridges.
