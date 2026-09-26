# Ticket 106: Fix dataclass mutable default for Python 3.11 compatibility

- **ID**: ticket-106
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-26

## Goal and scope

1. Fix dataclass field mutable default for `custom_providers` in `RuntimePolicyConfig` in `src/subllm/policy_config.py`.
2. Replace `MappingProxyType({})` direct default assignment with `field(default_factory=lambda: MappingProxyType({}))` to support Python 3.11+ dataclass validation rules.
3. Verify test suite and repository governance pass.

## Acceptance criteria

- [x] AC-01: `RuntimePolicyConfig` uses `default_factory` for `custom_providers` mapping default.
- [x] AC-02: Unit tests in `tests/test_policy_config.py` pass cleanly without `ValueError: mutable default`.
- [x] AC-03: SubLLM test suite and `./project/governance-check.sh` pass.

## Session authorization

User request "kolejno" authorizing execution of pipeline improvements, including the dataclass mutable default compatibility fix for Python 3.11.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
