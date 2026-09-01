# Ticket 026: Align the three-tier model catalog and TwinStudio routes

- Status: IN_PROGRESS
- Workstream: routing

## Goal

Finish the preserved model-catalog work by binding the declared August 2026
provider models to their exact direct transports, synchronizing operator
defaults, and registering TwinStudio's typed EDA requests in central routing.

## Acceptance criteria

- [x] Every declared tier-one and tier-two model has its exact direct provider
  binding; direct-only identifiers do not gain inferred OpenRouter aliases.
- [x] Built-in defaults and the operator-owned `subllm.toml` agree.
- [x] TwinStudio exposes `eda-nl2dsl`, `eda-firmware-audit`, and
  `eda-conflict-chat` through the central route catalog.
- [x] The complete repository verification suite passes on the integrated
  branch.
