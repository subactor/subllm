# Ticket 167: Integrate Cline Pass CLI transport for fast local task execution

- **ID**: ticket-167
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-28

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested to investigate and add `cline-pass` and ensure fast, working CLI shell tools are utilized instead of slow/failing local Ollama or throttled API routes. Implement opt-in Cline CLI transport (`src/subllm/cline_cli.py`) leveraging the operator's authenticated ClinePass subscription with deepseek-v4.1-flash-1017 in headless JSON plan mode (`-p`). Register `cline-cli` in `src/subllm/policy.py` candidate routes (`_DEFAULT`, `_REPAIR`, `_VALIDATOR`, `_CODING`) and verify unit boundaries.

## Acceptance criteria

- [x] AC-01: Implement `src/subllm/cline_cli.py` with private workspace, headless JSON plan-mode invocation, token usage extraction and robust terminal event handling.
- [x] AC-02: Register `cline-cli` provider and `cline-pass/deepseek-v4.1-flash-1017` model in `src/subllm/policy.py`.
- [x] AC-03: Add comprehensive unit tests in `tests/test_cline_cli.py` verifying argument handling, JSON parsing, error boundaries and token accounting.
- [x] AC-04: Pass all policy, resolver and cline_cli tests, and maintain governance compliance (`./project/governance-check.sh`).

## Verification

- `PYTHONPATH=src python3 -m pytest tests/test_cline_cli.py -q`: 8 passed in 1.61s.
- `PYTHONPATH=src python3 -m pytest tests/test_policy.py -q`: 110 passed in 1.08s.
- `PYTHONPATH=src python3 -m pytest tests/test_resolver.py tests/test_cli_transports.py -q`: 52 passed.
- Real local execution of `cline_cli.invoke` successfully verified against `cline-pass/deepseek-v4.1-flash-1017`.
- Governance check: `./project/governance-check.sh` passes cleanly (GOV-PASS: 0 errors, 0 warnings).

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
