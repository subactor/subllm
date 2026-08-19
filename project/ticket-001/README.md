# Ticket 001: Adopt POA CQRS ES API

- **ID**: ticket-001
- **Status**: DONE
- **HOME**: subactor
- **SHAPE**: both
- **ADOPT**: wellmanifest/poa, env-dsl, modularity, new-project, policy-dsl

## Goal

Keep `resolve()` as the policy core. Add a Process-Oriented Architecture
invoker so CLI, shell and localhost REST use the same closed query/command
bus, event journal and receipts.

## Acceptance

- Queries do not append events.
- Commands append `poa.event/v1` records with `secret_material_included=false`.
- Process URIs are registered; unknown URIs fail closed.
- HTTP binds locally and does not expose a generic shell.
- Catalog projection stays in `policy/adopted/poa/process-catalog.json`.

## Close

Closed (`DONE`) from integrated `main` after `54cfa26`. The POA CQRS/ES
invoker (`subllm poa`, `subllm serve`) is on the default branch. No
implementation files in this closure. The ticket stayed `IN_PROGRESS` on
`main` after the merge.
