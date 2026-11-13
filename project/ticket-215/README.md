# Ticket 215: Immutable request policy and worker ownership (S7)

- **ID**: ticket-215
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-13

SESSION_EXECUTION_AUTHORIZATION: continue implementation, testing and protected
merge of SUBLLM_TICKETS.md S7 (GitHub #213). maxActiveMinutes: 120.
Preserve the primary resolver.py edit and all foreign worktrees.

Reuse the existing policy parser, ContextVar audit graph, native route acceptance,
generation reservations, bounded HTTP workers and process-group cleanup. Add an
immutable policy snapshot, explicit audit profile and shared deadline/cancellation.
Keep worker-side policy validation; never expose an unrestricted execute path.
Linux parent-death capability is explicit, with fail-closed capability checks.

- [x] AC-01: Changed policy between resolution/dispatch or worker startup prevents HTTP and false snapshot success.
- [x] AC-02: Two concurrent profiles keep routes, archives, journals and caller correlation isolated.
- [x] AC-03: Parent SIGTERM/SIGKILL, normal worker exit with a live descendant, cancellation and shorter campaign deadlines stop owned effects.
- [ ] AC-04: Affected checks, full CI, governance and protected independent merge pass.

Raw receipts and continuity snapshots remain outside tracked source. The local
resolver.py delta is excluded from the scope. No PyPI upload is claimed.

Affected regression: 387 PASS. Final snapshot/profile tests: 9 PASS (overlapping
selection), including a source change during inference and native archive/journal
readback. Tests use real loopback HTTP, threads, subprocesses and parent signals.
Ruff, compileall, docs/report, logs and managed governance pass.

The request policy/audit/deadline API is explicit opt-in; legacy complete remains
compatible. Linux native OpenAI/Cursor/stream workers install parent-death
supervision. A strict ownership scope rejects CLI transports. Native pipe
cancellation is cooperative; persistence finalization can follow the inference
deadline, and arbitrary descendants escaping the owned group are not supported.
The source digest is checked before dispatch, independently at worker startup,
and again before native response acceptance. Accepted response/archive metadata
carries resolved_policy_sha256. A snapshot is constructed only by capture_policy.

Reuse discovery identified the autonom publisher's Linux ownership design and
the existing SubLLM Cursor subreaper/worker cleanup. No external implementation
was copied and no dependency was added. The shared lifetime helper now owns
native worker pipes and group cleanup before reaping the original leader.
Full CI and protected exact-head publication receipts remain external.
