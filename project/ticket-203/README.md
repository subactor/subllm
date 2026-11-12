# Ticket 203: Make packaging workstream ownership unambiguous

- **ID**: ticket-203
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **maxActiveMinutes**: 30

SESSION_EXECUTION_AUTHORIZATION: user requested continued technical implementation, testing and protected merging. PLF-22342 is a disjoint prerequisite for frozen PLF-22340, under PLF-22311. The published native allocator0.20.147 issued this canonical worktree and explicit writer binding agent:codex / codex-subllm-ownership-20261112t1547, revision1/fence1. Writer check passed; allocation alone grants no execution. Source stage15:43:28–16:13:28 UTC on2026-11-12, no renewal or reset.

## Scope and rationale

Remove only pyproject.toml from coordination.workstreams.governance.ownedPaths; retain integration ownership. The installed manifest projection explicitly excludes workstreams, and managed base has no workstreams key. No managed hashes/base, product source, packaging file, user resolver.py or native202 changes. The exact published adoption planner refuses conflicting governance/integration ownership; whole-package upgrade is a later dependent task.

## Acceptance criteria

- [x] AC-01: One packaging owner and unchanged managed pin; governance passes. Primary resolver.py/index/HEAD remain unchanged.
- [ ] AC-02: Protected native full CI and independent Validator exact-head review/merge pass. No production activation.
