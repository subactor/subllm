# Ticket 201: Durable caller-bound business cost journal

- **ID**: ticket-201
- **Owner**: codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **maxActiveMinutes**: 80

PLF-22329, PLF-22321 slice1. SESSION_EXECUTION_AUTHORIZATION: continued implementation, testing and protected merging. This bounded slice delivers the journal and cost export. The dependent gateway slice carries HTTP binding and real transport observations. Preserved draft: external recovery unsplit-source.tar and gateway-slice.patch.

The adopted validator accepts the native reservation; preserve its bytes. Newer allocator/controller compatibility remains PLF-22311.

## Acceptance criteria

- [x] AC-01: Durable case grants and request admission; replay/restart never duplicates events, pending/unknown fees block closure, explicit pricing/FX provenance, caller isolation and atomic exports.
- [ ] AC-02: Meaningful tests, actual Heyasa consumer validation, governance, native CI and independent protected merge.

## Scope split

The initial three public interfaces exceeded the M profile limit of two. Retained the journal and optional fixed-ID closure only. Gateway/client source and gateway tests were restored after a secret-scanned eight-file recovery snapshot. The accepted aggregate objective remains unchanged.

## Validation before publication

20 journal/ledger tests passed, Ruff passed, governance reported zero errors/warnings. Three synthetic exported events passed the current HeyAsa calculator and canonical JSON Schema. The independent native CI/review/merge boundary remains required; no production activation is claimed.
