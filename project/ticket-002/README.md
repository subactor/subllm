# ticket-002 - Register Supervisor routes in SubLLM

- Status: IN_PROGRESS
- Phase: PUBLICATION
- Workstream: application

## Goal

Make SubLLM the central source of truth for Supervisor assessment, delegation and review routes.

## Acceptance

- [x] `supervisor` is a declared SubLLM application.
- [x] `assessment`, `delegation` and `review` resolve through the central provider/model policy.
- [x] Runtime configuration contains the same bounded application identity.
- [x] Required verification passes: `SUBLLM_POLICY_FILE=$PWD/subllm.toml ./scripts/verify` (93 tests, package build).
- [ ] The exact reviewed head is merged through Validator Agent.
