# Ticket 126: Preserve explicit model selection within configured completion routes

- **ID**: ticket-126
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-20

## Goal and scope

Preserve explicit model selection when Willman calls the public SubLLM SDK.
The existing adapter detects supported arguments and currently drops `model`
because `complete` does not accept it. Add an optional model selector that only
narrows the application's existing, credential-qualified policy candidates.
Keep automatic application/function aliases compatible and prohibit silent
fallback to another model. Adaptive routes reject an unsupported explicit
selection before execution. No route, credential, budget or publication policy
is expanded.

SESSION_EXECUTION_AUTHORIZATION: the user requested continued autonomous
repair of Willman and its dependencies. The native allocator owns this exact
disjoint ticket/worktree and claimed lease; no peer lease is taken over.

## Acceptance criteria

- [x] AC-01: A requested model selects only matching existing policy candidates.
- [x] AC-02: Unknown/invalid models and unsupported adaptive selections fail before provider invocation; failures never fall back to another model.
- [ ] AC-03: Default aliases retain existing routing, affected tests and governance pass, and publication uses independent validation.

## Validation and deployment boundary

Canonical repository virtualenv: all 674 tests pass with the governance plugin;
Ruff passes for both changed Python files. Twelve new regression cases cover
explicit selection, same-model failover, unknown models, default aliases and
adaptive rejection. No live provider was called by these tests.

A separate attempted adapter canary correctly failed before inference on
central/SDK routing-contract drift (the deployed API lacks a current candidate
and the uncredited-cooldown execution field). Preserve this fail-closed check.
Align deployed packages after independent publication, then qualify the actual
provider/model. No current runtime or protected controller pin was modified.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
