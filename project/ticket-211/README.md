# Ticket 211: Return native completion audit receipts and persistence states (S4)

- **ID**: ticket-211
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-12

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested continued implementation,
testing and protected merge of SUBLLM_TICKETS.md. This ticket implements S4
(GitHub #210) using the existing native archive and journal. No publication
permission is inferred from local tests; the independent Validator owns merge.

maxActiveMinutes: 90

Reuse discovery: semcod/search indexed the local Subactor sources and identified
the existing SDK/archive path. Code inspection confirms interaction_context and
usage.record_attempt are the canonical writers; no storage wrapper or second
logger will be introduced. Preserve the primary resolver.py change and foreign
worktrees. PyPI dependency publication remains separately blocked.

## Acceptance criteria

- [x] AC-01: Immutable audit contains exact request/correlation identity and only acknowledged, readable native archive/journal references.
- [x] AC-02: Archive/journal failures and disabled capture preserve the provider result without an extra invocation; pending IDs alone never imply stored state.
- [x] AC-03: Two fallbacks, nested calls and concurrent requests keep their references isolated and correlation stable.
- [ ] AC-04: Affected regression tests, Ruff and managed governance pass; use protected local OneDev and independent exact-head review for merge.

## Tracking boundary

Local affected verification: 295 PASS, one existing PostgreSQL test skipped
because the local development database was unreachable. Four real child-worker
HTTP cases cover successful writes and each archive/journal failure combination.
Commit rollback, pending/forged/deleted archive rows, two fallbacks, nested
requests (including shared IDs), and eight concurrent requests are exercised.
Ruff, governance and exact-head publication receipts are checked separately.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 64/100 |
| Complexity | L |
| Estimated effort | 72 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
