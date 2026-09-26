# Ticket 105: Search and filtering in SubLLM usage web panel

- **ID**: ticket-105
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-25

## Goal and scope

1. Add search and filtering capabilities to the SubLLM web panel (`http://127.0.0.1:18988/`) and the underlying usage query endpoints.
2. Support text/keyword search across prompt messages, responses, caller/application, and models in `InteractionStore.query_attempts` (PostgreSQL) and `query_usage` (SQLite fallback).
3. Enhance `usage.html`, `usage.js`, and `usage.css` with a responsive search input, status indicator, and dynamic filter controls.
4. Add comprehensive unit and integration tests and verify that repository governance passes with exit code 0.

## Acceptance criteria

- [x] AC-01: Usage query API (`/v1/usage`) and `query_usage()` accept a `search` filter parameter without raising `USAGE-FILTER-001`.
- [x] AC-02: PostgreSQL interaction store (`InteractionStore.query_attempts`) filters attempts matching `search` within prompt requests, responses, models, or applications.
- [x] AC-03: Web panel UI (`usage.html`, `usage.js`, `usage.css`) provides a dedicated search input with submit/clear bindings and displays search results.
- [x] AC-04: Test coverage verifies search and filter parameters in usage API and interaction store.
- [x] AC-05: Test suite and `./project/governance-check.sh` pass.

## Session authorization

User explicit request "kolejno" authorizing execution of proposed improvements (including item 3: search and filtering in SubLLM web panel) treated as SESSION_EXECUTION_AUTHORIZATION.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
