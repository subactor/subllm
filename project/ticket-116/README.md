# Ticket 116: add openrouter glm-5.3-flash fallback across default, repair and coding routes

- **ID**: ticket-116
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-07

## Goal and scope

Add OpenRouter `glm-5.3-flash` fallback across `_DEFAULT`, `_REPAIR`, and `_CODING` route policies. This ensures that when OpenRouter is reached in fallback chains, fast and economical GLM-5.3 Flash is attempted before or alongside full GLM models, improving resilience against rate limits and timeouts on OpenRouter. Also update `_SZEPTNIK` routes to include `zai glm-5.3-flash` and `openrouter glm-5.3-flash`.

## Acceptance criteria

- [x] AC-01: `RouteCandidate(provider="openrouter", model="glm-5.3-flash", priority_offset=2)` is included in `_DEFAULT`, `_REPAIR`, and `_CODING` policies.
- [x] AC-02: `_SZEPTNIK` includes `zai glm-5.3-flash` and `openrouter glm-5.3-flash`.
- [x] AC-03: Resolver, client, and health test expectations are updated and pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
