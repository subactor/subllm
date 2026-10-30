# Ticket 184: Return client errors for invalid response contracts

- **ID**: ticket-184
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-30

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continue autonomous fixes, tests and independent
publication. The live promoted proxy refuses a malformed schema before a model
call, but returns HTTP 500. Classify invalid caller contracts as HTTP 400 and
prevent them falling through to raw upstream execution. Keep unavailable runtime
validators and failed server predicates as backend errors.

## Acceptance criteria

- [x] AC-01: Invalid contracts are HTTP 400 INVALID_REQUEST before any provider or upstream execution, for streaming and ordinary completion requests.
- [x] AC-02: Runtime validator/dependency failures remain HTTP 500, with no alternate unvalidated upstream generation; valid responses and failover remain intact.

Validation: 178 scoped HTTP, schema, quality, ordinary/adaptive completion tests
passed with governance enabled; three additional route variants confirmed that
server predicate failures never fall through to raw upstream. Ruff passed.
Protected exact-head CI and independent publication remain required.
