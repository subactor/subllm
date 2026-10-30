# Ticket 183: Enforce provider-declared JSON Schema before response acceptance

- **ID**: ticket-183
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-30

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continue the requested autonomous quality,
test and independent publication work. Existing response_format=json_schema
requests currently receive only JSON syntax checks. Apply their already declared
schema through the approved local validator before accepting a candidate answer.
An explicit quality_schema or task predicate must remain additionally required.
Keep provider wire format and model selection policy intact.

## Acceptance criteria

- [x] AC-01: A response violating its declared schema changes the model through native quality rejection while preserving wire format and paid accounting.
- [x] AC-02: Invalid descriptors cause no provider call; explicit local and declared schemas both apply, including bounded explicit-model and adaptive execution.

Validation: 213 scoped quality, schema, ordinary/adaptive completion, worker
and CLI/native transport tests passed with governance enabled. Ruff passed.
Protected exact-head CI and independent publication remain required.
