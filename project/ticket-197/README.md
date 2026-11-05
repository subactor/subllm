# Ticket 197: Preserve full local schema while projecting the Codex wire format

- **ID**: ticket-197
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-05

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continue, test, protected merge and deploy the central SubLLM route. Canonical PLF-25219 is a prerequisite of Platform PLF-25200. A real founder-query canary failed HTTP400 because the provider rejects uniqueItems; the same client/key/model completed the preceding structured probe. Preserve the original schema and full local uniqueness acceptance, while projecting only the unsupported keyword from strict Codex HTTP wire requests.

## Acceptance criteria

- [x] AC-01: Nested wire projections preserve caller data, property names and annotations; local uniqueness rejection/failover and unaffected transports/formats are covered.
- [ ] AC-02: Full verification, governance and independent exact-head publication pass.
- [ ] AC-03: The dedicated central API is updated under its own runtime lease and the existing typed gateway succeeds on a real founder query before guarded Control activation resumes.

## Tracking boundary

Raw provider exchange, live credentials and operational receipts stay outside tracked source. Platform gateway deployment is not replayed; Control remains unchanged until its recorded guarded operation.
