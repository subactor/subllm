# Ticket 212: Add policy bounded generation limits and shared output token budgets (S3)

- **ID**: ticket-212
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-12

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested continued implementation,
testing and protected merge of SUBLLM_TICKETS.md. This ticket implements S3
(GitHub #209). maxActiveMinutes: 90.

Reuse native routing, provider model parameters, response quality, S4 receipts
and native usage. semcod/search found existing timeout budgets; source inspection
found no shared generation budget. OpenAI, Claude and Google official protocol
references inform wire mappings; only synthetic loopback fixtures are executed.
The budget counts generated output (including reported thinking), not prompt
tokens or currency. Preserve resolver.py and foreign worktrees.

## Acceptance criteria

- [x] AC-01: Exact wire token limits for OpenAI legacy/reasoning, Anthropic and Gemini; preserve native attribution/audit.
- [x] AC-02: Strict positive integer limits and policy ceilings; unsupported transports fail before paid effect.
- [x] AC-03: Shared budget includes fallback and rejected/partial output, handles unknown usage explicitly and reserves concurrent calls safely.
- [ ] AC-04: Affected tests, Ruff, managed governance and protected independent publication pass; unlimited callers remain compatible.

## Tracking boundary

Local subsystem regression: 304 PASS, including routing, policy, custom providers,
adaptive routing, response quality and S4. Final generation/Gemini/audit checks:
97 PASS after conservative thinking-usage reconciliation. The isolated Cursor
descendant timeout test passes; one earlier full-run timing failure remains in
the external historical log. No assertion or timeout was relaxed.

Ruff passes. No live provider qualification or PyPI publication is claimed.
Independent exact-head review and protected merge remain external actions.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 64/100 |
| Complexity | L |
| Estimated effort | 78 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
