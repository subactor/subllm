# Ticket 093: Assign test dependency manifest to integration

- **ID**: ticket-093
- **Owner**: codex / sdk-ownership-20260920
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-19

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested continuation of the unified proxy delivery. Repair the missing ownership of the existing requirements-test.txt manifest introduced by governance adoption; this unblocks ticket-092. Add that exact path to integration. The new adoption also exposed a missing Docs adapter binding: verify the complete pinned managed inventory before passing its documentation copies to Docs. Keep modified or forged copies rejected.

## Acceptance criteria

- [ ] AC-01: The existing integration workstream owns requirements-test.txt; other ownership and gate settings are unchanged.
- [ ] AC-02: The Docs adapter accepts exact managed copies and rejects tampered files, forged locks and symlinks.
- [ ] AC-03: Full verification passes and the change is independently published.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
