# Ticket 098: Native transports for Gemini and Anthropic API with credential CLI

- **ID**: ticket-098
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-20

## Goal and scope

Add bounded JSON-over-HTTPS native transports for Gemini (generateContent) and Anthropic (Messages API) in `subllm.client`, with model catalog entries, failover handling for model 503 errors, and an atomic credential management CLI (`subllm env`).

## Acceptance criteria

- [x] AC-01: Native HTTP transports for `gemini-sdk` and `anthropic` with bounded timeouts, payload validation, and consistent error classification.
- [x] AC-02: Gemini catalog alignment (gemini-3.8-flash, gemini-3.6-flash, gemini-3.5-flash-lite, gemini-3.1-pro-preview) and model-scoped 503 failover.
- [x] AC-03: Credential store and CLI commands (`subllm env list|set|unset|verify|order|template`) with atomic writes, mode 0600, backup preservation, and no plaintext echo.
- [x] AC-04: Test suite passing with 100% ruff compliance and green governance check.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
