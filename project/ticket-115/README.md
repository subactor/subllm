# Ticket 115: add zai glm-5.3-flash fallback across default, repair and coding policies

- **ID**: ticket-115
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-07

## Goal and scope

Add `RouteCandidate(provider="zai", model="glm-5.3-flash", priority_offset=2)` fallback to `_DEFAULT`, `_REPAIR`, and `_CODING` route policy tuples so that all standard, coding, skills, and repair routes have fast in-provider fallback to Z.AI GLM 5.3 Flash when GLM 5.3 times out or fails before switching to external providers.

## Acceptance criteria

- [x] AC-01: `RouteCandidate(provider="zai", model="glm-5.3-flash", priority_offset=2)` is included in `_DEFAULT`, `_REPAIR`, and `_CODING` candidate tuples in `src/subllm/policy.py`.
- [x] AC-02: `configured_routes` tests confirm `zai glm-5.3-flash` appears as in-provider fallback for default, repair, and coding routes.
- [x] AC-03: All existing test suites pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
