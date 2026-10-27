# Ticket 155: Cache repeated Ollama model catalog reads

- **ID**: ticket-155
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION — continue shared caching of repeated provider API metadata using canonical dockuri/procache.

## Scope

Use the accepted optional Procache dependency for Ollama model catalogs. Preserve live health and inference, add explicit catalog freshness and bounded TTL/disable configuration. Validate model JSON before storing it. Preserve a single upstream attempt even when storage fails after transport. Do not cache authentication or routing health.

## Acceptance criteria

- [x] AC-01: Repeated valid catalogs reuse the canonical cache while origins, freshness and health remain separated.
- [x] AC-02: Actual adapter integration tests, existing proxy regressions, scoped lint and managed governance pass.
- [ ] AC-03: Exact-head protected publication and full native tests with the approved canonical dependency are observed.

All 62 catalog/proxy regression cases pass with the actual immutable canonical dependency. Coverage includes cold concurrent initialization, TTL expiry/disable, distinct upstreams, malformed payload rejection, server no-store, shared 429 cooldown, explicit HTTP freshness on both catalog endpoints and no duplicate transport after storage failure. Ambient authentication, cookies, custom identity headers and URL credentials bypass anonymous caching. Pinned dependency installation, scoped Ruff and managed governance pass. The matching OneDev profile is independently reviewed before activation; source tests do not silently skip the new adapter.
