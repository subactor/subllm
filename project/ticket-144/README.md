# Ticket 144: Admit GPT-6 Luna for governed Codex CLI task routing

- **ID**: ticket-144
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-25

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested deployment of GPT-6 Luna through
SubLLM/Codex and bounded pilots on existing Planfile work in semcod, paxlet-com,
subactor and maskservice. This source ticket admits the exact model to the
Codex CLI catalog and verifies operator-owned route selection. Publication
uses independent OneDev/Validator. Runtime activation and pilot queue effects
retain their separate controller leases and admission checks.

The session is bounded to 120 minutes from 2026-10-25T21:48:46Z. Existing
provider defaults remain unchanged; operators select Luna explicitly.

## Acceptance criteria

- [x] AC-01: A policy can select gpt-6-luna for codex-cli without API credentials.
- [x] AC-02: Resolver and completion preserve that exact model; unavailable
  transports and undeclared providers remain fail-closed.
- [x] AC-03: Regression tests and governance pass before protected publication.

## Validation

Full isolated suite: 886 passed, one optional PostgreSQL integration test skipped
with SUBLLM_USE_LOCAL_POSTGRES=0. With the shared local database enabled, that
test fails twice from a PostgreSQL statement timeout; tracked separately as
STARTER-030, not claimed passing. Ruff and governance pass; isolated wheel and
sdist build pass. Live canonical onedev-agent/code-edit completion returns
ROUTED_LUNA_OK through codex-cli/gpt-6-luna in 10.38 seconds. This proves model
routing, not completion of a real backlog task. Runtime/pilot continuation is
Willman PLF-20145. Independent CI/review remain required before merge.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
