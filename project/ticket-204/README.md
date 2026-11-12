# Ticket 204: Bound HTTP transports for SUBLLM_TICKETS S1

- **ID**: ticket-204
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **maxActiveMinutes**: 120

SESSION_EXECUTION_AUTHORIZATION: user requested implementation of the supplied SUBLLM_TICKETS.md. This ticket implements S1 only. Published native allocator 0.20.147 created the canonical branch/worktree and bound agent:codex / codex-subllm-s1-20261112, revision 1/fence 1. Allocation is not merge approval.

## Goal and scope

Harden the existing OpenAI-compatible and native HTTP transports: reject redirects and ambient proxies, bound reads before parsing, require finite timeouts and contain malformed/deep JSON. Preserve classification, attribution, routing and usage. Preserve the unrelated resolver.py changes in the primary checkout and all other writer scopes. Reuse native_http as the existing transport HOME; no second provider wrapper or paid test calls.

## Acceptance criteria

- [x] AC-01: Local 302/307/308 and environment-proxy fixtures show no redirect/proxy requests.
- [x] AC-02: Responses are bounded before parsing; oversized, slow/chunked, malformed and deeply nested responses fail safely without leaked credentials.
- [ ] AC-03: Focused and affected consumer tests preserve error classification, attribution and one transport attempt; run the managed governance gate.
- [ ] AC-04: Submit exact-head protected verification/review through declared local delivery; no direct merge or fabricated approval.

## Dependencies and remaining work

S2 release, S3 limits, S4 audit receipt, S5 cache, S6 streaming and S7 snapshot/process ownership remain separate implementation slices from the same user request. An existing expired reservation in ticket-199 owns tests/test_client.py; reconcile through the published custody process before any required fixture change there. Do not weaken production bounds to accommodate an outdated fixture.

## Verification checkpoint

87 focused transport/native tests PASS; Ruff PASS; managed governance PASS. Consumer suite: 91 passed / 3 failed; the Cursor descendant timing case subsequently passed isolated and on baseline. Two deterministic legacy mock incompatibilities remain in the reserved tests/test_client.py. The proposed minimal fixture patch passes both tests in an isolated copy. AC-03/04 remain open; no release or merge is claimed.
