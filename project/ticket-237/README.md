# Ticket 237: Enforce central local_only policy, monotonic deadlines and strict System One/forward contracts

- **ID**: ticket-237
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION
- **Created**: 2026-11-18

## Goal and scope

Implement the disjoint SubLLM reliability and offline-safety hardening items (`LLM-001`, `LLM-002`, `LLM-003`, `LLM-004`, `LLM-005` in `local_only`, `LLM-007`, `LLM-010`) across `policy_config.py`, `client_routes.py`, `runtime_profile.py`, `decisions.py`, `proxy_decide.py`, and `proxy_forward.py` with paired tests.

## Acceptance criteria

- [ ] AC-01: Central `execution_mode` (`standard` | `local_only`) blocks cloud/CLI discovery and adaptive failover before provider/credential lookup and is surfaced in `capabilities()`.
- [ ] AC-02: Shared monotonic deadline in `client_routes.complete` and chunked deadline-bounded reads in `decisions._post` distinguish `client_deadline_exceeded` from `backend_timeout`.
- [ ] AC-03: Strict System One decision parsing (`normalize_system_one_decision`) and native `d1` metadata (`decision_source`, `probability_kind`) eliminate fabricated `0.84` / default `true` / first-option coercions on bad outputs.
- [ ] AC-04: Strict forward JSON validation (`parse_strict_json_object`) and correlated forward telemetry (`correlate_forward_telemetry`) pass all existing and new tests, ruff, C901 <= 15 on all new/modified helpers, and governance gates.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
