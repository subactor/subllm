# Ticket 180: Refresh model routing audit for full GLM baseline and quality gates

- **ID**: ticket-180
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-30

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the operator requested continued routing
analysis and protected merges. The existing report still recommends Flash after
PR 183 restored the full baseline and introduced response-quality acceptance.
Update that canonical repository report, its digest-bound sidecar and index;
retain the original small-sample evidence and state production-quality limits.

## Acceptance criteria

- [x] AC-01: Versioned report describes the merged full-model baseline and actual quality/failover contract.
- [x] AC-02: Sidecar binds both historical measurements and reviewed quality source without claiming arbitrary semantic correctness or consumer rollout.
- [x] AC-03: Pinned docs/report validators and governance pass; request independent exact-head publication. Existing review-due warnings concern unchanged documents.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
