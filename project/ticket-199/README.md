# Ticket 199: Report accurate provider failure diagnostics

- **ID**: ticket-199
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-11
- **maxActiveMinutes**: 60

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested continued implementation and merging of SUBLLM_TICKETS.md and explicitly approved the one-field legacy repository identity correction. The published controller preserved the original metadata snapshot and handed this existing scope to agent:codex / codex-subllm-client-fixtures-20261112 at revision4/fence4. Scope and original intent paths remain unchanged.

Preserve accurate provider failure diagnostics when the bounded transport supplies a mandatory timeout and a bounded read size. Update only the two outdated mock signatures in tests/test_client.py. Preserve HTTP 402, truncation, fallback, body and credential assertions. No runtime diagnostic API or unrelated usage changes are introduced.

## Acceptance criteria

- [x] AC-01: Existing scope and controlled continuation are authorized by the user and the fenced controller handoff.
- [x] AC-02: The payment and truncated-response fixtures preserve their original outcome/fallback assertions on main and the bounded S1 candidate.
- [ ] AC-03: Required governance and tests pass before independent exact-head review and merge. Do not declare S1 or S2 complete from this fixture correction alone.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

Refs: S1 issue #208 and transport PR #216. The current transport full CI has 1406 passes and only these two mock incompatibilities. The proposal passed both tests in an isolated copy before custody recovery; the original file is qualified in this delivery.

Verification: both original tests pass on the current main baseline, and the same assertions pass against S1 a9f6243 using an isolated fixture copy. The only executable diff is the two fixture signatures. The original lease and ticket metadata are preserved in the controller handoff snapshot. No assertion or runtime behavior was weakened.
