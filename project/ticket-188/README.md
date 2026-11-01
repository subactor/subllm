# Ticket 188: Admit gpt-6-luna and 6.1-terra for OpenAI codex provider and default in szeptnik voice routes

- **ID**: ticket-188
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-01

## Goal and scope

Admit `gpt-6-luna` and `gpt-6.1-terra` under OpenAI API provider `codex`. Set `default_model = "gpt-6-luna"` in `subllm.toml` for `[providers.codex]`, update credential template, and prioritize `codex` / `gpt-6-luna` and `gpt-6.1-terra` candidates in `_SZEPTNIK` routes for voice/command steering in Heyasa.

SESSION_EXECUTION_AUTHORIZATION: user explicitly requested adding OpenAI API support for `codex` -> `gpt-6-luna` / `6.1-terra` and defaulting in heyasa.

## Acceptance criteria

- [x] AC-01: Admit `gpt-6-luna` and `gpt-6.1-terra` in `src/subllm/policy.py` for provider `codex`.
- [x] AC-02: Set `default_model = "gpt-6-luna"` for provider `codex` in `subllm.toml` and `credential_template.py`.
- [x] AC-03: Include `codex/gpt-6-luna` and `codex/gpt-6.1-terra` in `_SZEPTNIK` routes.
- [x] AC-04: Pass all policy and policy config tests and governance checks.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
