# Ticket 101: Record baseline standard pack adoption evidence

- **ID**: ticket-101
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-20

## Goal and scope

Record digest-bound adoption evidence for the baseline Wellmanifest standard
packs in `.governance/standard-adoption.json` and
`.governance/standard-pack-evidence/*.json`, following the
`semcod.standard-pack-projection/v1` receipt format used by other adopters.
Levels are claimed only where evidence exists: S4 where an active upstream
ruleset requires the successful conformance check, S3 where a successful
conformance run exists at the pinned revision, S2 for digest-pinned local
projections without a successful upstream CI receipt.

## Acceptance criteria

- [ ] AC-01: `.governance/standard-adoption.json` records all seven baseline
      packs (new-project, git-lifecycle, worktrees, merge,
      validation-attestation, ticket-lifecycle, logs) with immutable revisions,
      artifact digests and per-level evidence.
- [ ] AC-02: `.governance/standard-pack-evidence/*.json` files carry valid
      canonical CI and ruleset receipts bound to the pinned revisions.
- [ ] AC-03: `.governance/standard_pack_projection_check.py` verifies every
      record; `standard_pack_check.py` reports only the remaining upstream
      coverage gap (logs S3) in audit mode.
- [ ] AC-04: `./project/governance-check.sh` and `./scripts/verify` pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
