# Ticket 177: Route bounded LLM tasks to direct ZAI Flash

- **ID**: ticket-177
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-30

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the operator requested investigation of task/model
selection in subactor/subllm, specifically direct ZAI GLM 5.3 Flash versus GLM 5.3.
Prefer direct Flash with low reasoning for bounded assessment, NL-to-DSL, semantic
selection and completion. Preserve planning, coding, repair and review behavior.
Scope amendment: update existing policy expectations in tests/test_policy.py and tests/test_client.py in
addition to the new execution regression tests; this is the same application scope.

## Acceptance criteria

- [x] AC-01: Bounded roles prefer direct ZAI Flash with low reasoning, preserving both ZAI models and other providers.
- [x] AC-02: Planning, code editing, repair and review retain full GLM 5.3; explicit model and provider selection remains authoritative.
- [x] AC-03: 218 resolver/executor regressions, lint, docs/log checks and managed governance checks pass. Six paired live canaries returned correct results (3/3 per model); direct Flash availability also confirmed through the deployed proxy. Deployment is pending independent publication.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
