# Ticket 216: Preserve scoped request environment in streaming

- **ID**: ticket-216
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-13

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continue SUBLLM_TICKETS.md S7 implementation,
testing and protected publication. maxActiveMinutes: 120.

A real loopback probe after PR #226 found that streaming starts its generation
context from os.environ, rejecting a request-scoped policy when the global policy
differs. Reuse request_environment() at that boundary. Preserve independent
worker policy validation, explicit conflicting-policy rejection and legacy calls.
No dependency, worker environment, resolver.py or publisher changes.

## Acceptance criteria

- [x] AC-01: Complete and stream use scoped endpoints and credentials despite a different global profile, with actual loopback header and usage readback.
- [ ] AC-02: Explicit attempts to switch pinned policy still fail before HTTP; affected checks and protected exact-head validation/merge pass.

Regression reproduced before the change: 1 failed, 2 passed. After the change,
45 request-scope, streaming and worker-ownership tests pass. Actual HTTP headers
contain each scope's synthetic credential and both isolated journals record one
attempt. Explicit policy switching is rejected before any HTTP request. Worker
environment construction is unchanged: route endpoint/credential data already
travels through the closed validated JSON request. No operator credential is used.

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
