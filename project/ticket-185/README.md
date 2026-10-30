# Ticket 185: Report the installed package version from health endpoint

- **ID**: ticket-185
- **Owner**: agent:codex (session `codex-subllm-health-version-20261030`)
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-30

## Goal and scope

Correct the SubLLM proxy health response, which was hardcoded to `1.10.3`
while the installed distribution was `1.14.0`. Report the installed
`subactor-subllm` distribution version and use `unknown` if package metadata is
unavailable. Scope is limited to `src/subllm/proxy.py` and `tests/test_proxy.py`.

`SESSION_EXECUTION_AUTHORIZATION`: the user requested autonomous improvement
of the ecosystem and continued implementation, merging and testing across
turns. This ticket applies that standing authorization to the bounded health
metadata defect. Allocation is local only; protected validation and an
independent reviewer remain required for publication.

## Acceptance criteria

- [x] AC-01: `/health` reports the installed package version instead of a stale literal.
- [x] AC-02: Missing distribution metadata produces `unknown` without failing health.
- [ ] AC-03: Scoped tests, governance and protected exact-head validation pass.
- [ ] AC-04: Independent Validator approves and merges the exact tested head.

Validation to date: `tests/test_proxy.py` passed (68 tests), Ruff passed for
both changed Python files, and `project/governance-check.sh` passed. Protected
exact-head validation and independent publication remain pending.

## Tracking boundary

The ticket index is maintained by `project/readme.sh`. Private test and
deployment receipts remain outside Git.
