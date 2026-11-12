# Ticket 206: Synchronize authoritative version with existing package metadata

- **ID**: ticket-206
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **maxActiveMinutes**: 30

SESSION_EXECUTION_AUTHORIZATION: user requested continued technical work, tests and protected merging. PLF-22346 is a disjoint integration prerequisite for PLF-22343. The existing package and protected build already report1.14.0; VERSION remained1.13.0. The new standard correctly rejects that drift.

Explicit native caller agent:codex / codex-subllm-version-20261112t1614, revision1/fence1 passed writer verification. Canonical ticket/worktree issued by qualified published allocator0.20.147; allocation alone is not execution. Source stage starts2026-11-12T16:14:18Z and ends2026-11-12T16:44:18+00:00; no renewal or reset.

Change only integration-owned VERSION to match existing pyproject project.version. No new release or product-code change. Preserve active primary resolver.py, frozen202, other writer204, and the pending whole-adoption205 candidate.

## Acceptance criteria

- [x] AC-01: VERSION equals existing package1.14.0 and governance passes.
- [ ] AC-02: Protected full native CI and independent exact-head approval/merge pass. No production activation.
