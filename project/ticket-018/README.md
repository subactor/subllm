# Ticket 018: Register ecosystem LLM routes

- **ID**: ticket-018
- **Owner**: founder
- **Status**: ACTIVE
- **Workflow state**: IMPLEMENTATION
- **Created**: 2026-08-26

## Goal and scope

Register the remaining Semcod and Autogrammar LLM consumers in one central
SubLLM policy batch. This avoids private provider configuration and avoids one
PyPI release per consumer migration.

## Acceptance criteria

- [x] Every catalog entry has a stable public repository URL.
- [x] Every route uses an exact application/function pair.
- [x] Every new route inherits direct Z.AI `glm-5.3` as priority zero.
- [x] Cursor and OpenRouter remain pre-request fallbacks only.
- [ ] Publish the consolidated route catalog after the daily PyPI window resets.
