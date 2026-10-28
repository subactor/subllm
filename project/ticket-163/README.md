# Ticket 163: Index-compatible cache dependency metadata

- **ID**: ticket-163
- **Owner**: agent:codex / codex-index-metadata-20261028
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-28

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested continued backlog implementation, tests and protected merging. This bounded source continuation removes the reproduced direct-URL metadata blocker from subactor/subllm#20 while retaining approved Procache source and cache behavior. Current PyPI Procache availability is404; this source change does not claim publication.

## Acceptance criteria

- [x] AC-01: Built wheel/sdist have index-compatible Requires-Dist, exact Procache0.1.0, and immutable Git source only in development group.
- [x] AC-02: Real isolated base/cache installs and development resolver preserve approved dependency and all six route contracts without inference calls.
- [ ] AC-03: Native governance, exact-head OneDev and independent Validator publication qualify the source; parent release task remains open for actual publishing.

## Tracking boundary

Code remains IN_PROGRESS / PUBLICATION through independent merge. Protected external receipt owns terminal completion. No upload or tag is authorized by this source receipt.

## Validation evidence

Private package-qualification receipt confirms wheel/sdist and rebuild metadata, real base/cache installs, canonical cache hit and six unchanged route contracts. Real development group installation preserves the exact Git dependency commit.45 affected cache tests pass under Testless. No upload or inference calls. Required exact-head CI and independent approval remain pending.
