# Ticket 186: Last-resort provider probe when every candidate is cooling down

- **ID**: ticket-186
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-10-31

## Goal and scope

Requests must still be served by declared priority when providers fail. Today,
when every candidate is cooling down, SubLLM fails without any attempt, turning
a transient fault into an outage. Add a bounded last-resort probe: when no
healthy candidate remains, probe providers cooling for a transient reason in
priority order. Providers refused for credit or credentials (HTTP 401/402/403)
stay excluded. Observed trigger: agy (Gemini API) HTTP 402 depleted prepaid
credit, falling back to zai.

## Acceptance criteria

- [x] AC-01: Healthy providers keep priority; cooling ones stay hidden while any is healthy.
- [x] AC-02: When all are cooling transiently, they are probed in priority order within max_attempts.
- [x] AC-03: 401/402/403 cooldowns are never probed.
- [x] AC-04: Full suite passes (1235 passed, 2 skipped).

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
