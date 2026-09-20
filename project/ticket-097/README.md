# Ticket 097: feat(subllm): CLI transports for Claude Code and Antigravity agy, luna via codex-cli

- **ID**: ticket-097
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-20

## Goal and scope

SubLLM reaches Claude and Gemini models only through API keys (`claude` = Anthropic API, `agy` = Gemini API), while this
workstation authenticates through subscription logins (Claude Code, Google Antigravity `agy`) and its API accounts are
exhausted (z.ai weekly limit, OpenRouter balance). Only `codex-cli` had a local-login transport.

This ticket adds two CLI-authenticated transports next to `codex-cli`, sharing one hardened runner (`cli_common.py`):

- `claude-cli`: Claude Code print mode (`claude -p --output-format json`), e.g. `claude-sonnet-5`, `claude-opus-5`.
- `agy-cli`: Antigravity print mode (`agy --output-format json --print=...`), e.g. `claude-sonnet-4-6`, `claude-opus-4-6-thinking`, `gemini-3.1-pro-high`.
- Catalog: `gpt-5.6-luna` gets a `codex-cli` mapping (Codex login).

Both transports keep the `codex-cli` guarantees: fixed argv, private empty working root, environment allowlist without any API
key, byte and time budgets, whole process-group termination. No tools, no slash commands, no settings, no session persistence
(`claude`) and terminal sandbox with no permission bypass (`agy`). Non-text content fails closed.

Both providers are **off by default** (they spend a subscription): `enabled = false` in the defaults, and older operator
policy files that lack the two providers keep loading with them disabled. Enabling is configuration:
`[providers.claude-cli] enabled = true` in `subllm.toml` plus the provider in `SUBLLM_PROVIDER_ORDER`.

## Acceptance criteria

- [ ] AC-01: `claude-cli` and `agy-cli` complete through `subllm.complete()` with text, `json_object` and `json_schema` formats.
- [ ] AC-02: Neither provider is reachable unless enabled and listed in `SUBLLM_PROVIDER_ORDER`; existing policy files still load.
- [ ] AC-03: Tests cover argv, credential-free environment, budgets, timeout descendant reaping, error mapping and dispatch (442 pass).
- [ ] AC-04: Verified live on this workstation through `validator-agent/direct-pr-review`: `claude-sonnet-5` and `claude-sonnet-4-6`.

## Out of scope

`subllm.toml` in this repository (owned by another workstream) and the Validator client, which calls LiteLLM directly and
must call `subllm.complete()` for CLI routes.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
