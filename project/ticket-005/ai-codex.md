# Agent record: ticket-005

## Authorization

The active user request authorizes implementation, tests and protected
publication without a second confirmation.

## Plan

1. Add a standard-library OpenAI-compatible client.
2. Export typed response and error contracts.
3. Test direct Z.AI request shape and fail-closed transport handling.
4. Publish through exact-head Validator review.
5. Expose the integrated completion API through a closed stdin-JSON adapter so
   Supervisor can consume SubLLM-owned transports and bounded failover.

## Result

- Added typed zero-dependency completion execution.
- Verified direct Z.AI GLM 5.3 request shape without network credentials.
- Passed 114 tests, Ruff, compileall and package build.
- Added a bounded machine adapter with no secret fields, shell, command or
  model-selection input.
