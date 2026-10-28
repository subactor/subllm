# Ticket 169: Record CLI provider fallback analysis and pending default-route config

- **ID**: ticket-169
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-28

SESSION_EXECUTION_AUTHORIZATION: the user asked to find other ways to use LLM providers (Codex, Claude, Antigravity, Cline) while Z.AI is rate-limited, then answered "do it" to the recommended plan (CLI fallbacks plus demoting Z.AI).

## Goal and scope

Record the analysis in `docs/analysis/cli-provider-fallback.md` and retain the pending tracked change as a durable dependency. The `subllm.toml` change itself is blocked by the `application` workstream limit (tickets 145, 150, 168 active) and is not part of this ticket.

## Acceptance criteria

- [x] AC-01: The analysis records provider probe results, root cause, the operator overlay actually applied, and its limits.
- [x] AC-02: The pending `subllm.toml` / `policy.py` work is listed as a recommendation with its blocker.
- [ ] AC-03: Docs checker, governance gate and protected publication pass.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose and raw command logs are not required delivery output.
</Content>
