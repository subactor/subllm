# Ticket 118: Honor caller environment in SubLLM provider health isolation

- **ID**: ticket-118
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application
- **Created**: 2026-10-08

## Goal and scope

Prerequisite of willmux PLF-125 / issue314. Explicit SDK completion callers can pass an isolated SUBLLM_HEALTH_STATE_FILE in environ, but health resolves only os.environ. Willman's existing local policy adapter already isolates a subprocess and sets its process environment; that adapter is not the reproduced faulty path. Honor the caller overlay for persisted health reads, failure/success writes and observation/reset, and keep unavailable-store fallback memory scoped to that path. Default callers retain process environment behavior. Four allowed source/test files; no provider policy edits, credentials, global fleet grants, live worker activation or deployment.

## Acceptance criteria

- [x] AC-01: Regression proves caller-scoped persisted health and fallback are isolated; completion reads and updates the correct store, respects cooldown/fallback and leaves global state unchanged. Existing health/client and full tests plus governance pass.
- [ ] AC-02: Exact-head source published through local OneDev and independent Validator, or precise protected blocker preserved. Runtime upgrade and full autonomous coding canary remain separate.

## Authorization

SESSION_EXECUTION_AUTHORIZATION: User requested continuing autonomy repair and previously testing/publishing/protected merging. This session is the primary writer of ticket118. Existing policy ticket117 and blocked willmux214 are preserved. Lease uses controller CAS/fencing; limits120minutes total, implementation and validation within this four-file scope. Model selection policy and unknown work remain owned by their existing writers.

## Local validation

Seven new isolation regressions; four initial reproductions failed before the repair. Focused health/client suite44PASS after rebasing to the current target and adding the empty-probe regression. Earlier full native repo environment579PASS with two existing MCP deprecation warnings; exact final-head full-suite counts are recorded externally. Ruff checks actual files with --no-respect-gitignore, compile and isolated wheel/sdist build pass; governance0errors0warnings. Global Python full-suite collection was blocked by a different MCP version; repo venv mcp1.28.1 was used instead. Repo venv no-isolation build lacked setuptools; declared build dependencies were installed by the isolated build without changing shared runtime. Real readonly LLM isolation canary and exact source publication receipts are stored outside the ticket. Live coding-agent remains on its separately pinned release until a protected activation is qualified.
