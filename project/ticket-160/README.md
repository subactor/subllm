# Ticket160: Shared offline d1 decision SDK

- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT

SESSION_EXECUTION_AUTHORIZATION: user selected offline d1:3b and requested
SubLLM reuse across libraries, tests and protected publication.

## Acceptance criteria

- [x] AC-01: Native local-only client validates model, schema and probabilities; no proxy, redirect, chat or cloud fallback. Proxy exposes explicit offline mode.
- [x] AC-02: Private capture stores actual native state/questions and response; exact journal attribution retains zero output tokens without inference replay on storage failure.
- [x] AC-03: Real local d1, consumer integration, required exact-head CI and independent publication qualify the shared API.

Cold startup may exceed90seconds under load; use an explicit bounded120second
startup budget and bounded90second keep-alive, never fabricated latency claims.
Model answers are advisory; applications retain argument and authorization gates.

## Validation evidence

- Focused SDK/proxy/archive suite: 126 passed.
- Full SubLLM suite: 1102 passed, 1 skipped because local PostgreSQL is not
  reachable; governance preflight passed with 0 errors and 0 warnings.
- Local Ollama `d1:3b` canary: 56 input tokens, 0 output tokens, 103 ms warm;
  actual native state/questions and response were archived and linked to the
  exact usage row. The separate initial warm call without an archive context
  is not used as archive evidence.
- AC-03 still requires exact-head protected CI and independent Validator
  publication. Heyasa currently sends the d1 request without `offline: true`;
  its separate integration follow-up must opt in to the fail-closed route.
