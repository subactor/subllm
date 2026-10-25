# Ticket139: Avoid native writer DDL deadlocks during historical indexing

- **ID**: ticket-139
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: continued autonomous fixes, tests and protected delivery requested by the user. Material follow-up to issue146/142 after ticket138 source was independently published and its failed runtime attempt stopped/checkpointed with source lease released. Session starts2026-10-25T13:04Z, maximum120 minutes. Inputs change through a proven native-writer DDL fix and protected runtime promotion before any new recovery; no unchanged retry or cleanup. Preserve canonical52892 and artifact52899 on leaf24630; exact failed replacement52943 is the sole new recovery target.

- [x] AC-01: Owned before/after fixture proves native InteractionStore writers no longer issue recursive parent-index DDL when it already exists, preserving actual namespace and first-use creation/serialization. Reproduced SQLite same-file thread contention is serialized within the unchanged5s lock-wait budget.
- [x] AC-02: Exact database/OID/owner/definition/digest-pinned replacement recovery preserves original/artifacts and rejects stale, healthy, conflicting, constraint, active or extra-artifact targets; no auto retry/cleanup.
- [ ] AC-03: Focused/full stack/governance and independent exact-head publication pass with unchanged provider result handling and5000ms query deadline.
- [ ] AC-04: Resolve protected runtime writer promotion before a changed bounded live recovery; all35 partition indexes and native caller-query readback pass before closing142/146. Source publication alone is incomplete.

Validation milestone:78 focused cases pass, including native writer metadata/namespace guards, genuine PostgreSQL interrupted-replacement recovery, SQLite FIFO multi-instance writers and all available multiprocessing start methods. Owned before-control on published main reproduces native writer timeout; the corrected PostgreSQL fixture passes with query/payload/search/pagination parity and preserved original/artifacts. Initial full-stack failure reproduced the existing SQLite concurrency case on both unchanged main and branch; same-inode FIFO serialization now passes it without extending its5s lock budget. Final full stack passes:887 tests,1 skip, plus Docs/Logs, Ruff, compile and sdist/wheel build. Independent exact-head publication remains pending. Runtime remains11/35 and no unchanged live recovery is authorized.

Independent review follow-up:the initial POSIX-only skip marker was rejected. Process-isolation coverage now executes every multiprocessing start method available on the host, including spawn/forkserver, without adding a skipped test. The additional observed local-writer starvation was corrected with FIFO admission; final full stack887 passed/1 existing integration skip.
