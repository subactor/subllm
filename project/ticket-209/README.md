# Ticket 209: Preserve gateway HTTP diagnostics with bounded transport fixtures

- **ID**: ticket-209
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-12
- **maxActiveMinutes**: 45

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested SUBLLM_TICKETS.md implementation. S1's full CI exposed a legacy gateway opener mock that rejects the required timeout keyword. This ticket updates that one fixture signature, preserving all status/body/credential assertions and the existing transport bounds. Native allocation bound agent:codex / codex-subllm-gateway-fixture-20261112. No other writer's client fixtures or source are edited.

## Acceptance criteria

- [x] AC-01: The gateway refusal fixture accepts the opener timeout keyword and preserves both credential-redaction assertions.
- [x] AC-02: Both parametrizations pass on main and against the S1 candidate without relaxing assertions or retrying HTTP.
- [ ] AC-03: Managed governance and independent exact-head delivery pass; preserve the separate ticket-199 custody dependency.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

Refs: S1 #208 and draft PR #216. The original hosted S1 Python 3.13 job recorded 1404 passes and four failures: two client fixtures reserved by ticket-199, plus two parametrizations of this gateway fixture. This ticket addresses only the gateway signature.

Verification: both parametrizations passed on main ec62460 and against S1 359ba32 using an isolated fixture copy and the pinned Wellman 0.23.0 execution runtime. One inherited Starlette/httpx deprecation warning is reported. Runtime behavior, assertions and transport bounds are unchanged.
