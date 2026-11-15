# Ticket 218: Bound usage journal admission and preserve fork safety

- **ID**: ticket-218
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-15

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested continuation, testing and protected merge. Existing parent PLF-22332, delivery dependency PLF-22390. maxActiveMinutes: 120.

The usage journal currently uses one unbounded threading lock for every database. A paused writer can block an unrelated journal, withhold an already-produced provider result, and leave a fork child waiting on an inherited locked gate. Reuse the existing inode-scoped, fork-reset SQLite admission with the current usage budget of 0.5 seconds shared between local queueing and SQLite waiting. Preserve the archive's five-second default, strict/best-effort failures, private storage and exactly-once provider calls. Runtime promotion and wider cold-start/worker issues remain outside this source slice.

## Acceptance criteria

- [x] AC-01: Paused-writer regressions show independent journal progress, bounded strict rejection and unchanged provider result without retry.
- [ ] AC-02: Real fork persistence, default archive budgets, affected tests, full stack, native CI and independent publication pass.

Validation before publication: isolated regression confirms unrelated-writer and fork blocking in the old global gate. After reuse of the native gate, 15 new behavior/budget cases pass. The affected suite passes 248 tests with one optional PostgreSQL skip on private tmpfs; 161 usage/archive tests pass under coverage accounting. A persistent-filesystem run was interrupted after confirmed ext4 journal commit stalls and its failures are retained, without a waiver. Full scripts/verify, native CI and independent approval remain required. Test connection replacements are scoped to their owning module so coverage keeps its independent SQLite connection.
