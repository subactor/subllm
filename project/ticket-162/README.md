# Ticket 162: Accept d1-ultra as an explicit offline decision model name

- **ID**: ticket-162
- **Owner**: agent:opencode
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-10-28
- **Authorization**: SESSION_EXECUTION_AUTHORIZATION — the user asked to use the local Liquid AI `d1-ultra` decision model offline through Ollama for routing, add it to SubLLM and reuse it from other libraries.

## Goal and scope

The offline decision SDK accepted exactly one model name, `d1:3b`, and rejected
every other name. A host that serves the same Liquid AI decision family under
`d1-ultra` therefore had to masquerade its model as `d1:3b` to be usable at all,
which hides the real deployed identity from the usage journal and from callers
such as Heyasa.

This ticket makes the served decision model set explicit instead of implied: a
named module constant lists the accepted local decision models, a single
resolver normalizes only the bare `d1` alias and fails closed on everything
else, and the regression suite covers both accepted names plus the still-refused
lookalikes. The local-only, no-fallback, zero-output-token invariants are
unchanged: nothing here reaches a chat model or a remote provider, and model
concentration stays advisory rather than authorization.

## Acceptance criteria

- [x] AC-01: `d1-ultra` and `d1:3b` are accepted as explicit local decision model
  names, and the requested name is forwarded unaliased to the native endpoint so
  the usage journal records the deployed identity.
- [x] AC-02: The bare `d1` alias still normalizes to `d1:3b`, and every
  unlisted name (`d1:cloud`, `d1-ultra:latest`, `qwen3.5:0.8b`, `other/d1:3b`)
  is rejected before any transport, preserving the no-fallback invariant.
- [x] AC-03: Focused regressions and the managed governance gate pass.

## Validation

- `python3 -m pytest tests/test_decisions.py -q` -> 56 passed.
- Live local check against Ollama: `resolve_decision_model` accepts `d1-ultra`
  and `d1` (-> `d1:3b`), rejects `d1:cloud`, and `decide_legacy` with
  `model="d1-ultra"` returned `{'selected_operation': 'op_1'}` for the query
  `zrestartuj serwer` with `input_tokens=51, output_tokens=0`.
- Protected publication goes through local OneDev verification and the
  independent Validator only; runtime activation is a separate observed effect.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
