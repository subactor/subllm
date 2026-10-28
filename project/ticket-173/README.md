# Ticket 173: Guard gateway stdio tests against mcp major drift

- **ID**: ticket-173
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-28

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user asked to remove recurring verification
failures. `tests/test_gateway_stdio.py` fails on a clean `main` when run with the global
interpreter (a conda base environment with `mcp 2.1.1`) because the pyproject pins
`mcp==1.30.0`. The bridge then never exits after an upstream failure, which surfaced as
four unrelated 5 s subprocess timeouts. In the project venv (`mcp 1.28.1`) the same file
passes 8/8. The cause is dependency drift, not a bridge or test defect.

Test-only change; no production code is modified.

## Changes

- `tests/test_gateway_stdio.py` reads the pinned major version from `pyproject.toml`
  and skips the module with an explicit reason when the installed `mcp` major differs.

## Acceptance criteria

- [x] AC-01: Under a different `mcp` major the module is skipped with a reason naming both versions.
- [x] AC-02: Under the project environment all 8 gateway stdio tests still run and pass.
- [x] AC-03: `./project/governance-check.sh` passes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
