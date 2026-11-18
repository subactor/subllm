# Ticket 226: SUB-02 decide: no silent remote fallback for local System One decisions

- **ID**: ticket-226
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18

## Goal and scope

Repair plan SUB-02 (claude-review 2026-11-18): with `offline: false`, a failing
local decision model made `/v1/decide` send the decision state to
`{app}/{func}`, defaulting to the cloud chain `heyasa/command`.

- Remote fallback only with an explicit boolean `allow_remote_fallback: true`;
  otherwise `503 LOCAL_DECISION_UNAVAILABLE` with the reason, `provider: null`
  and `X-Subactor-Remote-Fallback: refused`, and no provider attempt.
- A request without `X-Subactor-Application`/`X-Subactor-Function` is attributed
  to `subactor-proxy/decide` and cannot fall back without a declared route.
- An explicitly requested registered model or route behaves as before.

## Acceptance criteria

- [x] AC-01: `tests/test_proxy.py` covers Ollama 500 with and without fallback.
- [ ] AC-02: Governance check and exact-head review pass.

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
