# Ticket 242: Wire strict legacy D1 results into the HTTP decision response for Planfile GITHUB-373

- **ID**: ticket-242
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-24

## Goal and scope

Connect the existing strict System One normalizer to the HTTP handler. Keep native results calibrated and issue success receipts only for accepted responses. Tracker semcod/planfile issue 373.

## Acceptance criteria

- [x] Invalid and ambiguous text responses return a typed error, without a success receipt.
- [x] Label-only answers preserve their choice, logical value or score and report unknown probabilities. Native D1 preserves its validated result and provenance.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 60/100 |
| Complexity | M |
| Estimated effort | 51 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
