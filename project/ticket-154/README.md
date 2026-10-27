# Ticket 154: Adopt optional canonical Procache dependency

- **ID**: ticket-154
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION — continue shared caching of repeated provider API metadata using dockuri/procache.

## Scope

Provide the optional `cache` extra and the same test dependency pinned to accepted dockuri/procache commit 7fe316c9b0ac45d9747ddf90afc7c7969084cbb1. Keep the default installation dependency-free. Application wiring is a separate owned implementation.

## Acceptance criteria

- [x] AC-01: Both extras resolve the exact immutable canonical Procache revision.
- [x] AC-02: Wheel metadata and managed governance pass; independent native CI verifies the existing complete suite.
- [ ] AC-03: Exact-head independent protected publication is observed.

## Validation

The isolated checkout environment installed the dependency from the canonical HTTPS Git URL. Installed direct_url metadata binds the accepted commit; the new HTTP adapter imports and incomplete credential scope bypass is verified. The wheel contains the cache/test conditional requirements and no unconditional runtime dependencies. Wheel build and managed governance pass. Required native and hosted checks remain unchanged.

The same stable actor retired its expired ticket144 writer only after exact trusted merge, ancestry and liveness observations. Prior source/runtime files and old worktrees remain preserved. Ticket154 has its own new controller fence; the retirement grants no review or merge approval.
