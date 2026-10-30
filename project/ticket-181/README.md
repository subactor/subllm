# Ticket 181: Declare JSON Schema validation as a runtime dependency

- **ID**: ticket-181
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-30

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: continue the user-authorized autonomous quality,
test and independent publication work. Declare the existing jsonschema 4.26.0
pin as a runtime dependency so a normal package installation can supply the
upcoming opt-in local response schema check without relying on test extras.
This dependency slice changes no model or response behavior.

## Acceptance criteria

- [x] AC-01: The built wheel requires jsonschema 4.26.0, and an isolated installation without test extras imports both SubLLM and jsonschema.

Validation: built wheel installed with its runtime dependencies in a new virtual
environment without pytest or test extras. JSON Schema accepted a matching
object and refused an incorrect enum value. Protected CI and independent
Validator publication remain required.
