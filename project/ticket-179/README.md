# Ticket 179: Validate response quality before failover and retain full GLM baseline

- **ID**: ticket-179
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-30

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the operator requested preserving full GLM 5.3
when Flash quality is uncertain and adding response-quality checks with model
fallback on rejected results. Keep full GLM as the baseline until representative
quality evidence supports a cheaper default. Apply structural checks to every
completion and an optional task-owned semantic validator before accepting it.

## Acceptance criteria

- [x] AC-01: Bounded routes retain full GLM 5.3 with low effort; explicit model/provider choices remain authoritative.
- [x] AC-02: Empty, truncated and malformed structured responses are rejected before success, with model-scoped fallback and paid usage retained.
- [x] AC-03: 238 focused tests and 52 scoped tests under coverage passed before the final additional adaptive validator-error regression. Live ZAI full-model canary passed task acceptance in 5.535 s. Task rejection does not quarantine unrelated prompts; validator defects abort.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
