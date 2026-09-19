# Ticket 076: Disable dead cursor provider

- **ID**: ticket-076
- **Owner**: human:founder
- **Status**: DONE
- **Workflow state**: PUBLICATION
- **Created**: 2026-09-18

SESSION_EXECUTION_AUTHORIZATION: 2026-09-18, owner asked to disable cursor
provider due to 1528 consecutive provider_unavailable failures. GitHub
allocation: issue #76.

## Goal and scope

Provider `cursor` in `subllm.toml` fails with `provider_unavailable` on every
call (1528 consecutive failures measured 2026-09-18 in `provider-health.json`).
It sits as the second candidate in every `_DEFAULT`, `_REPAIR`, `_VALIDATOR`,
`_CODING`, and `_CODE_CONTEXT` route, wasting an attempt on every invocation.

This ticket sets `enabled = false` in the shipped `subllm.toml` operator
configuration. The change does not touch `src/`, `VERSION`, or `pyproject.toml`,
so `SUBLLM_SOURCE_DIGEST` remains unchanged and no consumer pin migration is
required. The mounted policy takes effect on service restart.

Cursor as an IDE (driven by `gillm`) is unaffected — that uses a different
mechanism in a different layer.

## Acceptance criteria

- [x] AC-01: `subllm.toml` has `enabled = false` for `[providers.cursor]` with
      reason and date comment.
- [x] AC-02: Tests that assert cursor is available in default policy are updated
      to reflect `enabled = false`. Cursor-specific transport tests use an
      `enabled_cursor_policy` fixture that provides an isolated policy with
      cursor re-enabled.
- [x] AC-03: Full test suite passes (330/330).
- [x] AC-04: `compileall` and `check-docs-report` pass.

## Non-goals

- Re-enabling cursor: requires verifying account access and endpoint health
  first, then setting `enabled = true` with evidence from `provider-health.json`.
- Changes under `src/` (issue #75: urlopen timeout, reasoning response, max_tokens).
