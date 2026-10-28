# Ticket 165: Validate routing against a single fresh policy snapshot

- **ID**: ticket-165
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-28

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested continuation, tests and protected independent publication of SubLLM backlog and request/response diagnostics work.

Private profiling identified 67 policy reads in one validation during collector ingestion. Reuse one fresh snapshot across that validation and avoid producing unused route evidence. Preserve public routing selection, digests, checks and fresh configuration observation across calls. Do not claim this eliminates SQLite storage latency or all 0.5-second client timeouts.

## Acceptance criteria

- [x] AC-01: Single policy read per validation; stale state is not reused across validations; invalid routes remain rejected; public candidate and digest behavior remains compatible.
- [ ] AC-02: Focused tests, offline before/after measurements, governance and exact-head protected CI pass; independent Validator approves and merges.

## Evidence

Private fixture/profile and measurements: private session receipt `subllm-usage-ack-20261028`.

Local validation: 216 focused tests passed; native governance, Ruff and dependency checks passed. Offline measurements for 66 routes reduced policy reads from 67 to 1 per validation; five-call median changed from 145.7 ms to 8.47 ms. All 611 public candidates and evidence digests remained byte-equivalent. This is validation latency, not an end-to-end collector latency guarantee.
