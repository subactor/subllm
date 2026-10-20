# Ticket 125: Bounded code-edit context and progress

- **ID**: ticket-125
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION

SESSION_EXECUTION_AUTHORIZATION: the user requested continued repair and autonomous verification of Willman and dependencies on 2026-10-20. The user explicitly authorized preserving the unrelated .env backup in a private external archive; native allocation then created this canonical branch, scope and local claim. The final index step was recovered using private TMPDIR after the shared /tmp filled; no second ticket was allocated.

Issue: https://github.com/subactor/subllm/issues/124. A previous Willman attempt spent its deadline selecting full-repository context and produced no source change. Supply a bounded host scope and cap all logical context-completion calls, including schema/selection retries. Context metadata narrows reads and writes but grants no writer, review or merge authority; the host retains native admission and publication. Provider-internal HTTP retries remain owned by the completion router and are not claimed as separately budgeted calls.

- [x] AC-01: A worktree/HEAD/native-intent-bound explicit scope snapshots only supplied read/write files, preserves extractor pins and ignore policies, and rejects stale, malformed, escaping and symlinked scope before a model call. Read-context files cannot become write targets.
- [x] AC-02: One context-call budget covers inventory, detail, reduction and response retries; completed/failed attempts remain inspectable on later failure.
- [x] AC-03: Correlated safe progress is visible through SDK callback and CLI stderr JSONL while successful stdout remains one JSON result. Sink failure cannot repeat a completion.
- [x] AC-04: Regression and real pinned-extractor checks pass with the normal governance plugin; no paid provider calls are needed for qualification. Host integration, independent merge and runtime deployment remain separate stages.

Validation on 2026-10-20: focused compatibility/scope/progress suite 95 passed; full suite 662 passed with the normal governance plugin and an isolated disposable PostgreSQL database (48.02 s). The first full run against the ambient development database had 661 passes and one SQL statement timeout; the unchanged main version of that single test subsequently passed in 40.98 s. No timeout was waived or retry result substituted for the first observation. Ruff over src/tests with --no-respect-gitignore, git diff --check and governance all pass.

A real pinned code2dsl extraction on the preserved Willman ticket-287 fixture observed 690 files / 33,412 records / 6,947.89 ms for the full snapshot, versus 2 files / 320 records / 965.35 ms for the explicit write-seed-only snapshot; canonical IDs agree. This is one extractor measurement and a context-size lower bound, not proof that the complete dependency context fits two files. Selection used a deterministic fake completion (11 versus 6 logical queries); paid model calls: zero. Raw qualification evidence stays in private recovery storage at scope-qualification.json. Auxiliary extractor processes now inherit their parent's private scratch directory without credential inheritance.

Publication uses the independently configured OneDev profile and Validator for the exact head. This change supplies the optional context API and default call budget; it does not yet make the coding-agent host pass its accepted scope or establish production task completion. Issue #124 remains open for that integration and rollout.
