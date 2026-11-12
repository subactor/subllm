# Ticket 214: Add native inference streams with cancellation feedback and proxy delivery (S6)

- **ID**: ticket-214
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-12

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continue implementation, tests and protected
merge of the supplied SUBLLM_TICKETS.md, S6 (GitHub #212).
maxActiveMinutes: 90. Preserve the primary resolver.py edit and foreign worktrees.

Reuse native route selection, response acceptance, generation reservations,
audit/archive/journal writers, worker policy validation and process-group cleanup.
Add one stream interface for OpenAI-compatible, Anthropic and Gemini APIs, plus
incremental OpenAI/Ollama proxy formatting. Use bounded native SSE decoding,
worker pipes and a bounded consumer queue; never replay a paid request after
provider output. Feedback binds request/epoch/sequence and can request cancel or
a new request, never silently edit an in-flight prompt or its acceptance rules.

Chunks are provisional. The controller owns atomic code checkpoints and their
base/spec/environment/test-manifest binding. No generic resume, tool execution,
live paid qualification, whole-Forge p95 or hard real-time claim is made.

## Acceptance criteria

- [x] AC-01: Actual native deltas arrive before completion on all three API dialects; immutable event IDs/order and terminal native audit/usage are preserved.
- [x] AC-02: Partial/invalid JSON, disconnects, duplicate/out-of-order events, unknown terminal usage, saturation and cancellation never produce false success or a second inference after output.
- [x] AC-03: Feedback rejects stale identities/epochs/sequences; tool fragments remain provisional and cancellation ends the worker; SDK timings and invalidated output tokens are measured honestly.
- [ ] AC-04: Both proxy protocols flush live deltas, preserve terminal receipts and cancel slow/disconnected clients; affected tests, governance, full CI and independent protected merge pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

Native SDK/proxy suite: 29 PASS, with actual worker pipes and three native HTTP
dialects (Anthropic/Gemini through isolated local TLS). Twenty synthetic
SDK/controller cycles bind immutable code and fixed tests to base, spec and
environment hashes. Their measured p95 was 0.79 seconds; this is a local test
observation, not whole-Forge performance qualification. Invalidated output cost
retains known provider counters and stays unknown without terminal usage.

Reuse search found the existing request builders, route quality/generation
contracts, audit writers and grouped worker cleanup; no runtime dependency was
added. Local receivers test both reset connections and stalled socket writes.
Rendezvous guards allow slow startup without extending cancellation assertions.
Ruff, compileall, docs/report, logs and managed governance pass. Exact logs,
benchmarks and protected publication receipts remain external. No paid-provider
qualification or PyPI upload is claimed.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 64/100 |
| Complexity | L |
| Estimated effort | 90 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
