# Ticket 213: Add opt-in exact completion cache with native replay receipts (S5)

- **ID**: ticket-213
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-12

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continue implementing, testing and protected
publication of the supplied SUBLLM_TICKETS.md, S5 (GitHub #211).
maxActiveMinutes: 90. Preserve the primary resolver.py edit and foreign worktrees.

Reuse procache's pinned SQLite cache and singleflight, native complete routing,
quality gates, S4 receipts and InteractionStore. Cache only explicitly opted-in
plain-text API requests; no CLI, tool effects or adaptive routing. Require an
operator account scope, model revision, acceptance version and positive TTL.
Cache waits are bounded and inference must fit procache's 120-second flight.
Cached responses are validated again, retain separate historical token usage,
and create a native completion_replay archive without an inference journal row.

## Acceptance criteria

- [x] AC-01: Exact-key miss/hit and restart produce one inference/journal row and two distinct native operation receipts.
- [x] AC-02: Scope, credentials, model/revision, policy, generation parameters and acceptance changes invalidate; current quality checks always apply; force generation bypasses reuse.
- [x] AC-03: Concurrent misses, owner cancellation, corruption, expiry and cache failure after inference preserve results without duplicate effects.
- [ ] AC-04: Affected regression, Ruff, managed governance and protected exact-head independent review/merge pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

Initial S5 suite: 45 PASS. Affected routing, audit, generation, quality and HTTP
regression: 230 PASS. Final cache/input-snapshot and native usage checks are
running; their exact result and independent publication receipts remain external.
semcod/search identified dockuri/procache tests and its existing SQLite flight
implementation. Runtime reuse retains the immutable dependency pin already in
this repository. Ruff, docs/report, log and managed governance checks pass.
No live paid provider qualification or PyPI publication is claimed.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 64/100 |
| Complexity | L |
| Estimated effort | 66 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
