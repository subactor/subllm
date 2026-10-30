# Ticket 182: Reject task schema mismatches before completion success

- **ID**: ticket-182
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-30

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continue the user-authorized autonomous quality,
test and independent publication work. Add optional local quality_schema to the
Python completion API and its closed stdin JSON adapter. Compile the bounded
2020-12 schema before paying, keep references offline, and reject wrong candidate
answers through the existing model-scoped quality gate. Wire response_format
remains unchanged. Schema checks do not claim semantic truth.

## Acceptance criteria

- [x] AC-01: A schema-mismatching answer selects the next allowed model, records paid usage, and does not quarantine the provider. Invalid or unsupported schemas fail before any provider call.
- [x] AC-02: Python, stdin JSON and adaptive calls preserve schema acceptance, task predicates, wire format and explicit model restrictions.

The runtime dependency slice ticket-181 must publish before this feature.

Validation: 96 scoped schema, quality, CLI, explicit-model and adaptive tests
passed with the native governance hook enabled. Ruff passed. Runtime dependency
ticket-181 is independently merged in PR185. Protected exact-head CI and
independent publication remain required before deployment.
