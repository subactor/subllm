# Ticket 245: Avoid per-write WAL DDL and fsync stalls in usage journal under parallel SDK calls

- **ID**: ticket-245
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-26

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: User requested continuation, repair, and protected merge ("kontynuuj") for `subactor/subllm#256`. This bounded application slice operates only inside `src/subllm/usage.py` and `tests/test_usage.py`.

`tests/test_sdk_archive_link.py::test_parallel_sdk_calls_do_not_exchange_capture_references` intermittently failed (`7 == 8`) in OneDev with `WARNING subllm.usage:usage.py:155 SubLLM usage journal unavailable; completion result preserved`. Under parallel SDK calls, every `usage.record_attempt()` invocation entered the 0.5-second FIFO `_sqlite_write_slot`, re-ran `PRAGMA journal_mode=WAL` and 5 schema/DDL checks, and committed with SQLite's default `PRAGMA synchronous=FULL`, causing 7 sequential per-commit `fsync()` waits to exhaust the 0.5-second admission window for the 8th thread.

Track initialized journal `(st_dev, st_ino)` inboxes with fork-safe reset (`os.register_at_fork`), use `PRAGMA synchronous=NORMAL` (preserving WAL durability guarantees and existing 0.5-second admission cap from `ticket-218`), and self-heal if an already-cached inode loses the `attempts` table.

## Acceptance criteria

- [x] AC-01: After first successful initialization of a usage journal inode, subsequent `record_attempt()` calls skip redundant `PRAGMA journal_mode=WAL`, `CREATE TABLE/INDEX`, and `PRAGMA table_info` DDL while setting `PRAGMA synchronous=NORMAL` and preserving `budget_seconds=0.5`.
- [x] AC-02: Dropping `attempts` on an already-initialized journal inode triggers bounded schema re-initialization and succeeds; 4 waves of 8 parallel SDK usage writes persist all 32 attempts.
- [ ] AC-03: Targeted usage/archive tests, Ruff, `compileall`, `./project/governance-check.sh --base origin/main`, `wellman check`, OneDev `onedev/local-verify`, and independent `app/ifuri-validator-agent` approval/merge pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
