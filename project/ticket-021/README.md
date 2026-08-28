# Ticket 021: Governed process DSL editor

- **Status**: IN_PROGRESS / PUBLICATION
- **Workstream**: runtime

## Goal

Expose a closed POA URI that turns an LLM-authored edit list into a
digest-bound candidate process DSL without changing the registered process or
granting execution authority.

## Acceptance

- The editor accepts only paths declared editable by the source process.
- Identity, actions, deterministic controls and publication gates cannot be
  changed by an LLM proposal.
- The exact base digest, candidate digest, event journal and terminal receipt
  bind every accepted proposal.
- Unknown paths, stale bases, no-op edits and secret-bearing documents fail
  closed.
- CLI/HTTP consumers continue to share `PolicyBus`; no generic shell or file
  mutation is introduced.

## Evidence

- `./scripts/verify`: Ruff, compile, 158 tests and sdist/wheel build passed.
- Cross-repository integration: skills-agent `repair.v1` schema 1.1 was edited
  through the registered URI, producing distinct base/candidate digests and a
  receipt; Repair loaded the candidate and used its changed attempt budget.
