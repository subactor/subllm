# Ticket 202: Bind gateway attempts to business cost observations

- **ID**: ticket-202
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **maxActiveMinutes**: 30

PLF-22330, second slice of PLF-22321. SESSION_EXECUTION_AUTHORIZATION: user requested continued implementation, testing and protected merging. Scope is exactly the gateway, actual-attempt seam and their new integration tests. Native201 journal is already merged in accepted base171989a.

## Ownership and execution boundary

Published native allocator v0.20.147 (511eb0ab), qualified with3 dirty-primary scope tests, created the canonical202 branch/worktree. The target's installed standard remains0.20.38; no managed hashes or active primary files changed. Explicit caller agent:codex/session codex-subllm-gateway-20261112t1438-01a1ca3f, revision1/fence1, passed the published writer checker. Allocation alone is not execution authorization. Preserve the user-confirmed active resolver.py edit. No lease transfer or timeout takeover occurred.

Only this owned ticket branch fast-forwarded from allocator base517ab5a to the already merged journal171989a. The primary HEAD/index/file bytes stayed unchanged. Source stage is bounded from14:38:43 to15:08:43 UTC on2026-11-12; no renewal or source-stage reset is authorized.

## Acceptance criteria

- [x] AC-01: Authenticated server-granted case references reject foreign/unregistered requests before provider calls. Every actual provider/failover attempt is correlated with the correct business case and wire model.
- [x] AC-02: Observation admission fails before paid work; post-call observation failure neither repeats nor replaces its result. Compile and unmeasured calls preserve their behavior; context bindings do not leak. Unknown fees remain incomplete.
- [ ] AC-03: Scoped tests, governance, protected native CI and independent exact-head review/merge pass. Production activation remains PLF-22322.

## Diagnostic evidence

The preserved candidate passed10 gateway tests and Ruff.140 existing regressions passed across the broad run and corrected fixture setup;2 failures also reproduce on the unmodified base and are tracked in PLF-22332. They are not waived. Actual checked-in source still requires scoped and protected native verification.

## Actual source verification

Actual gateway integration tests completed10 cases successfully; the30-case gateway/journal/ledger run is still finishing its existing journal cases on the loaded host. Ruff and governance passed. Freeze source and use the mandatory full protected OneDev profile before independent review; retain the final local result externally.
