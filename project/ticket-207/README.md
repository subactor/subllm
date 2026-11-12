# Ticket 207: SubLLM API generations and integration status

- **ID**: ticket-207
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **maxActiveMinutes**: 90

SESSION_EXECUTION_AUTHORIZATION: the user requested the seven tasks in SUBLLM_TICKETS.md. This integration slice delivers the explicitly requested S2 API/migration matrix and a canonical source/evidence/status report. It preserves source work in ticket-204 and the existing packaging/adoption owners. No publication, closure or implementation of S3-S7 is inferred from a backlog entry.

## Acceptance criteria

- [x] AC-01: Compare the verified PyPI wheel with the current Git API, keeping declared range, selected lock and observed API distinct.
- [x] AC-02: Document optional scanner versus isolated worker profiles and migration gates without forcing consumer dependency upgrades.
- [x] AC-03: Map S1-S7 to real upstream issues, record implementation/proposal/blocked states and index both canonical documents.
- [x] AC-04: Validate metadata, placement, index and managed governance; report any inherited managed-copy or publication gap without editing standard hashes.

Validation: pinned docs checker PASS with independently verified external managed-copy hashes; managed governance PASS. Candidate S1 wheel/sdist verifier, offline installs, pip check, 87 transport tests and one public complete()/archive fixture PASS on both Python 3.11 and 3.12. This documentation does not close the remaining runtime or release tasks.
