# Ticket 219: Avoid loading the full SDK before native worker startup

- **ID**: ticket-219
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-15

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user requested continuation, tests and independent publication. Continue PLF-22332 in the allocator-owned canonical checkout. Base: 973936e35d93c95d0c526f22e4405c74525ce2c7.

Importing a native worker currently loads the completion client and proxy before worker ownership or SDK execution. Three fresh published-source observations load252 modules and take0.234–0.311s on this host. Resolve public API exports on first access, retaining their names and exact canonical object identities. Preserve the existing provider_order and request_scope callable/module-name behavior.

## Acceptance criteria

- [x] AC-01: Fresh package and native-worker imports do not import the completion client, proxy, decisions or KPI ledger. Every existing public export remains available with its original identity; star import, dir and callable aliases work in fresh processes.
- [ ] AC-02: Existing real worker timeout, descendant cleanup and owner-death tests pass with unchanged deadlines and no new skip. Full declared checks, exact head/base OneDev CI and trusted independent publication succeed.

## Boundaries

No resolver, routing policy, credentials, provider calls, runtime promotion, dependency changes or test timeout expansion. The current service checkout and user resolver remain untouched. Reduced import work does not guarantee scheduling or persistent-disk latency.
