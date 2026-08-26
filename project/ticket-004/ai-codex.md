---
participant-id: agent:codex
participant: codex
role: agent
ticket: ticket-004
---
# Participant: Codex

## Finding

Version 1.3.0 updated route candidates and `subllm.toml`, but not the packaged
`_DEFAULTS`. A wheel installed outside the monorepo therefore selected Cursor
and advertised Z.AI GLM 5.2.

## Change

- Align built-in provider priorities and models with the repository policy.
- Add an isolated no-policy-file regression test.
- Publish the correction as 1.3.1.
