# Ticket 131: Honor configured adaptive aliases at the gateway

- **ID**: ticket-131
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-24

SESSION_EXECUTION_AUTHORIZATION: user asks to continue testing, fixing and protected publication of cached priority-first API failover. Coordination STARTER-141; source session codex-subllm131-gateway-aliases-20261024t1950 ends by 21:10Z. This application scope is disjoint from source128/129/130 and the existing STARTER-140 runtime guard; preserve their work and ownership.

## Goal

The direct HTTP proxy understands operator-defined adaptive aliases, but the authenticated gateway rejects those exact names with400 before dispatch. Use only validated configured names, keep registered application/function route precedence, retain the existing direct-model response_format restriction and expose configured names consistently in the model catalog. No provider, credential, dependency, policy or production binding changes.

## Acceptance criteria

- [x] AC-01: Configured aliases, including vendor/name IDs, appear once in the model catalog and execute through the existing class-bounded direct dispatcher; the response reports the actual model.
- [x] AC-02: Unknown names, missing/invalid alias policy and unsupported formats cause no upstream call. Registered named routes retain precedence.
- [x] AC-03: Focused regressions, owned real HTTP failover/cache/restart checks, stack and managed governance checks pass.
- [ ] AC-04: Native exact-head independent publication completes; no direct merge or competing runtime/source writer.

## Verification

Four new regression cases reproduced the defect before the fix; four negative/precedence cases already passed. All57 focused tests, seven owned real HTTP cases, the full stack suite (701 tests), build and managed gate passed. The PostgreSQL test fixture was removed. No paid API calls or production service changes. The ContextVar test handle was renamed to avoid a managed secret-scan false positive on a code expression.
