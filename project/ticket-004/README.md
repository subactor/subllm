# Ticket 004: Align packaged defaults with direct Z.AI GLM 5.3

- **ID**: ticket-004
- **Owner**: founder
- **Status**: ACTIVE
- **Workflow state**: PUBLICATION
- **Created**: 2026-08-26

## Goal and scope

Make the wheel's built-in provider policy identical to the validated repository
policy: direct Z.AI GLM 5.3 first, Cursor second and OpenRouter third. This fixes
public installations that do not have a local `subllm.toml`.

## Acceptance criteria

- [x] AC-01: Built-in Z.AI priority is 0 and its default model is `glm-5.3`.
- [x] AC-02: Built-in Cursor and OpenRouter priorities are 20 and 30.
- [x] AC-03: A no-policy-file test covers the packaged defaults and canonical Todo2code URL.
- [ ] AC-04: Verification, Validator merge, GitHub release and PyPI 1.3.1 publication succeed.

## Evidence

- Public 1.3.0 smoke test selected stale Cursor defaults only when no repository policy file was available.
- Root cause: `src/subllm/policy_config.py::_DEFAULTS` had not been updated with `subllm.toml`.
