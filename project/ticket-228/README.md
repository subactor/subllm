# Ticket 228: SUB-03 System One: request timeout, keep_alive and warmup for cold local models

- **ID**: ticket-228
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-18

## Goal and scope

Repair plan SUB-03 (claude-review 2026-11-18, after SUB-02): the local decision
attempt had a hard `min(timeout, 6.0)` and `decide()` a fixed `keep_alive=90`, so the
first decision after idle lost to a cold d1/qwen load on an 8 GB GPU.

- Local attempt timeout from the request (`timeout`, capped at 120 s; 6 s default).
- `keep_alive` from the payload (0-300 s or `45s`/`5m`) reaches native
  `/v1/systemone` and the Ollama chat path; invalid values return 400.
- `POST /v1/decide/warmup` loads the local decision model and reports
  `load_duration_ms`.

## Acceptance criteria

- [x] AC-01: `tests/test_decisions.py` covers timeout, keep_alive and warmup.
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
| Estimated effort | 54 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
