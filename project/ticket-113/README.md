# Ticket 113: fix usage detail 404 and handle sqlite attempt ids

- **ID**: ticket-113
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-07

## Goal and scope

Fix 404 errors on `/v1/usage/detail?id=<id>` when operating with SQLite attempt IDs,
ensuring attempt metadata is returned when detailed interaction payloads are not
available, and optimize frontend `usage.js` to avoid redundant failing requests.

## Acceptance criteria

- [ ] AC-01: `/v1/usage/detail` handles integer attempt IDs from SQLite attempts journal and returns attempt metadata.
- [ ] AC-02: `usage.js` safely handles missing request/response payloads without repeated 404 console spam.
- [ ] AC-03: Tests verify query_interaction_detail and endpoint behavior for both PostgreSQL interaction records and SQLite attempt IDs.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
