# Ticket 008: Allow bounded runtime tuning of attempt deadlines

- Status: IN_PROGRESS
- Workflow state: PUBLICATION
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
- [x] Full verification passes with 203 tests; protected publication is pending.
- [ ] Live Supervisor readback succeeds without residual attempt workers.
