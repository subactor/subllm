# Ticket 111: Adaptive quota recovery and model class substitution

- **ID**: ticket-111
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: on quota exhaustion test remaining enabled providers, persist availability and reprioritize future requests. External pinned models receive available class-compatible replacements. Strong requirements must not silently fall back to weaker or unknown models. Operational class mappings are explicit policy, not benchmark claims.

## Acceptance criteria

- Persist bounded probe outcomes, avoid repeated sweeps and respect disabled providers and request budgets.
- Match requested model class and response format; expose actual provider/model.
- Exercise quota recovery, unavailable pinned models, class constraints, concurrency and protocol failures in tests.
- Run governance and protected publication; verify local API deployment.

## Validation

- 134 focused routing/CLI/API tests passed; 37 proxy/adaptive regressions passed after the custom-provider fix.
- Full suite: 565 passed; the one environment-sensitive default-policy test passed with session timeout overrides removed.
- Live synthetic HTTP 429 triggered real Cursor, Antigravity and Codex probes. The next request reused availability without repeating the quota request. An unavailable strong-model alias selected Gemini and detected the deliberate arithmetic bug.
- Lint and governance passed. Protected publication pending.
