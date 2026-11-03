# Ticket 192: Register Heyasa autonomy routes in SubLLM policy

- **ID**: ticket-192
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-11-03

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: Register the `heyasa` application and its canonical autonomy routes (`command` and `decision-routing`) in SubLLM policy.
When the Heyasa assistant dispatches decisions or commands through SubLLM (e.g. via `subllm-cursor-api` or direct library calls), requests targeting `heyasa/command` and `heyasa/decision-routing` must resolve cleanly using standard route policies without throwing `UnknownRouteError`.

## Acceptance criteria

- [ ] AC-01: `heyasa` is registered as an ApplicationSpec in `subllm.policy.APPLICATIONS`.
- [ ] AC-02: `RoutePolicy("heyasa", "command", _DEFAULT)` and `RoutePolicy("heyasa", "decision-routing", _DEFAULT)` are present in `subllm.policy.ROUTES`.
- [ ] AC-03: `subllm.resolver.route_policy("heyasa", "command")` and `subllm.resolver.route_policy("heyasa", "decision-routing")` resolve successfully and return valid configured routes.
- [ ] AC-04: Unit tests verify that `heyasa/command` and `heyasa/decision-routing` are recognized and pass full policy validation.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
