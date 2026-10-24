# Ticket 134: Validate calibration reports before ranking

- **ID**: ticket-134
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: user requests autonomous backlog execution, immediate fixes for encountered defects, testing and protected merge. A direct historical-clock reproducer confirmed issue138; two other model-advisory claims are rejected by existing code. This source scope is disjoint from active ticket133. Session bounded60 minutes from2026-10-24T22:05Z.

- [x] AC-01: Missing or non-object sample/result data produces structured calibration errors instead of KeyError/TypeError.
- [x] AC-02: Bounded report/sample shapes, endpoint/attempt binding and metric/accounting invariants are validated before ranking.
- [x] AC-03: Valid generated success, failed and dry-run reports retain behavior; negative penalties and altered models remain rejected. No provider call is used.
- [ ] AC-04: Relevant regressions, Ruff/governance, independent exact-head validation and protected merge succeed.

Validation:73 calibration/routing regressions pass, including the malformed-report reproducer, endpoint membership, metrics/accounting, legitimate failure/dry-run and existing negative-penalty/model guards. Historical genuine six-sample report is accepted under its historical clock; its missing-result variant now raises CompletionError. Ruff passes. No provider request was made. Independent publication remains AC-04.
