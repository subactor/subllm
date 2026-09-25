# Ticket 104: Store full LLM prompts and responses in PostgreSQL interaction store

- **ID**: ticket-104
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-25

## Goal and scope

Persist full LLM interaction details (messages/prompts, responses, tokens, duration, status, and diagnostic metrics) into a PostgreSQL database, accessible locally in the development environment.

## Acceptance criteria

- [x] AC-01: SubLLM supports PostgreSQL interaction storage with prompt and response payload persistence.
- [x] AC-02: Local development configuration resolves PostgreSQL DSN from `SUBLLM_POSTGRES_DSN`, `SUBLLM_DATABASE_URL`, or `SUBLLM_GATEWAY_DATABASE_URL`.
- [x] AC-03: Direct completions and proxy completions record full interactions when PostgreSQL interaction store is configured.
- [x] AC-04: Usage dashboard on port 18988 / API displays prompt and response details for stored interactions.
- [x] AC-05: Test suite passes with exit code 0 and governance checks pass.

## Session authorization

User explicit request: "zmien architekture subllm, aby uzywał bazy danych postgresql i w niej zapisywal wszystkie sczegoly, ktore beda dostepne dla mnie lokalnie w srodowisku deweloperskim" treated as SESSION_EXECUTION_AUTHORIZATION.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
