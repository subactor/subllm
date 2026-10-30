# Ticket 178: Document task model routing audit and direct Flash canaries

- **ID**: ticket-178
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-30

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the operator requested a task/model routing audit
of SubLLM, including direct ZAI Flash versus the full model. This integration
workstream owns the canonical analysis and its required Report sidecar; runtime
and test changes belong to ticket-177. Adding the required sidecar is a bounded
documentation scope amendment within this objective.

## Acceptance criteria

- [x] AC-01: Report distinguishes source routing, live attempts, latency, task correctness, quota and deployment.
- [x] AC-02: Report is indexed and bound to a validated evidence manifest; documentation, report conformance and managed governance checks pass. Raw observations and credentials stay outside Git.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
