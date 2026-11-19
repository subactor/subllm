# Ticket 241: Restore configured provider models in the HTTP discovery catalog

- **ID**: ticket-241
- **Owner**: unresolved:human
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-19

## Goal and scope

During rollout on the NVIDIA workstation, the published wheel omitted the operator-configured model `qwen3:8b` from HTTP discovery. Each HTTP request runs on its own thread. Load the active policy in the discovery request context so both catalog formats include configured models. Preserve local Ollama tags and the existing cache directives.

## Acceptance criteria

- [x] AC-01: Both discovery endpoints return the custom provider model on their first request and reflect a policy change on the next request.
- [x] AC-02: An unreadable or invalid policy produces an explicit HTTP error.
- [ ] AC-03: Compare the old and new catalogs against the workstation configuration and run the proxy tests.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 52/100 |
| Complexity | M |
| Estimated effort | 51 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
