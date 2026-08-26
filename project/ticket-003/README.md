# ticket-003 - Prefer direct Z.AI GLM 5.3 for all SubLLM routes

- Status: IN_PROGRESS
- Phase: PUBLICATION
- Workstream: routing

## Goal

Make public SubLLM the central routing authority and prefer direct Z.AI GLM 5.3
for every registered application/function route.

## Acceptance

- [x] Z.AI has the highest provider priority and defaults to `glm-5.3`.
- [x] Every built-in route resolves direct Z.AI GLM 5.3 first.
- [x] Cursor and OpenRouter remain pre-request fallbacks only.
- [x] The complete verification suite and package build pass (`110 passed`).
- [ ] The frozen reviewed head is merged through Validator Agent.
