# Ticket 225: Register autonom local application routes (SUB-09)

- **ID**: ticket-225
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION — user requested continuing the supplied 2026-11-18 Planfile repair plan, including implementing and testing eligible next tasks through governed delivery.

## Goal and scope

Implement the bounded SUB-09 slice: register the `autonom` application and its
local decision/routing functions in the existing SubLLM policy, so callers can
resolve explicitly attributed local-provider routes. Do not add a cloud
fallback or define undocumented bind/verify/synthesize APIs; those require
separate accepted contracts.

## Acceptance criteria

- [x] AC-01: `autonom` is a validated application with its own repository identity; its declared `decide` and `llm-ask` routes resolve using explicitly local providers only.
- [x] AC-02: Absent, disabled, or unconfigured local providers fail closed without inheriting the default cloud route; other application routes remain unchanged.
- [x] AC-03: Focused policy tests and the managed governance gate pass in this ticket worktree.
- [ ] AC-04: Exact-head OneDev verification and independent Validator publication pass.

## Scope decisions

- The plan-provided `AUT-002` is already marked done; do not duplicate that
  decider change.
- `SUB-09` only lists `decide`, `bind`, `verify`, `synthesize`, and `llm-ask`
  as candidate URI functions; no SubLLM endpoints are accepted for all five.
  This ticket registers only the existing policy surface (`decide` and
  `llm-ask`) and leaves new bind/verify/synthesize procedures out of scope.
- Routes are local-only (`ollama`, `minis`) and carry the explicit `autonom`
  application/function attribution. No credentials, service startup, deployment,
  usage of real account data, or cross-repository edits are included.

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
| Estimated effort | 54 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
