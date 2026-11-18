# Ticket 227: Test proxy version in source-only and installed environments

- **ID**: ticket-227
- **Owner**: agent:codex / codex-sub10-proxy-version-20261118t1328z
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-18

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continue the exported Planfile tasks. SUB-10 / STARTER-042 covers the proxy health-version assertion and documentation of its source-only test environment.

## Acceptance criteria

- [x] AC-01. Run the proxy suite from source without distribution metadata.
- [x] AC-02. Run the same suite with the package installed and verify its reported version.
- [ ] AC-03. Request protected publication.

All 79 proxy tests passed in a source-only environment without distribution metadata and again against the installed 1.14.0 wheel.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 48/100 |
| Complexity | M |
| Estimated effort | 47 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
