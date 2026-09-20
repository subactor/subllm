# Ticket 100: Synchronize wellmanifest standards

- **ID**: ticket-100
- **Owner**: devin
- **Workstream**: governance
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-20
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION; user requested continuation and standards synchronization.

## Goal and scope

Synchronize and upgrade wellmanifest governance standards across `subactor/subllm`:
- Upgrade `wellmanifest/new-project` from 0.20.35 to 0.20.38 via Goal adoption updater.
- Synchronize `wellmanifest/docs` standard projections to latest 0.6.0.
- Synchronize/pin lifecycle standards (`git-lifecycle`, `ticket-lifecycle`) and `logs` / `wellm`.
- Establish target-owned `ticket-activity.override.json` with `missingPolicy: git-ancestry` so merged deliveries are resolved cleanly.
- Ignore ephemeral and debugging logs (`*.log`) in `.gitignore`.
- Run complete verification suite (`scripts/verify`, `project/governance-check.sh`, `standard_pack_check.py`).

## Acceptance criteria

- [ ] AC-01: `wellmanifest/new-project` upgraded to 0.20.38 with updated manifest, lock, and governance tools.
- [ ] AC-02: Target-owned `ticket-activity.override.json` deployed to resolve merged deliveries via Git ancestry.
- [ ] AC-03: `wellmanifest/docs` standard artifacts updated to 0.6.0.
- [ ] AC-04: `.gitignore` ignores `*.log` to prevent local logs from dirtying working tree.
- [ ] AC-05: `./project/governance-check.sh` and `./scripts/verify` pass with zero errors.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
