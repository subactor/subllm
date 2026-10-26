# Ticket 147: Default Codex and Codex CLI routes to GPT-6 Sol

- **ID**: ticket-147
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-26

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested that SubLLM select the newer
`gpt-6-sol` model on the `codex` / `codex-cli` lane instead of `gpt-5.6-sol`
(`"(p=11) -> codex/gpt-5.6-sol (p=15"` -> `codex/gpt-6-sol (p=15)`).

This ticket admits `gpt-6-sol` to the `codex` and `codex-cli` providers in
`src/subllm/policy.py`, updates the `codex` and `codex-cli` route candidates
and repository `subllm.toml` provider defaults to `gpt-6-sol`, updates the
credential template documentation for `codex` and `codex-cli`, and preserves
`gpt-5.6-sol` in the model catalog for Cursor (`cursor/gpt-5.6-sol`) and
backward-compatible explicit selection.

## Acceptance criteria

- [x] AC-01: `gpt-6-sol` is registered in `MODELS` for `codex` (`openai/gpt-6-sol`)
  and `codex-cli` (`wire_model="gpt-6-sol"`), and is never exposed as an
  OpenRouter model.
- [x] AC-02: Shared routes (`_DEFAULT`, `_REPAIR`, `_VALIDATOR`, `_CODING`) and
  `subllm.toml` default `codex` (p=15) and `codex-cli` (p=16) to `gpt-6-sol`
  while keeping `cursor` on `gpt-5.6-sol` and `src/subllm/policy_config.py`
  untouched to avoid active scope overlap with `ticket-145`.
- [x] AC-03: Focused unit and governance checks pass on the ticket worktree.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
