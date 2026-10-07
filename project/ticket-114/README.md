# Ticket 114: cache uncredited and exhausted provider status across attempts

- **ID**: ticket-114
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: VALIDATION
- **Created**: 2026-10-07

## Goal and scope

Cache uncredited (HTTP 402 Insufficient credits, HTTP 401/403 Invalid key) and exhausted quota/rate-limited (HTTP 429) provider responses with extended cooldown periods (default 3600s / configurable up to daily checks, e.g. SUBLLM_UNCREDITED_COOLDOWN_SECONDS or provider failure reason tiers) so that subsequent completion attempts do not repeatedly probe dead or exhausted accounts across every request, but retry at most a few times a day while continuing to use other available providers with valid credits/quotas.

## Acceptance criteria

- [x] AC-01: HTTP 402 (insufficient credits) and auth failures (HTTP 401/403) apply extended cooldown (default 3600s / configurable) instead of short default cooldown (60s).
- [x] AC-02: Health state preserves specific failure reasons (`http_402`, `http_401`, `http_403`, `http_429`) and enforces appropriate cooldown period per failure class.
- [x] AC-03: Configuration support via environment (`SUBLLM_UNCREDITED_COOLDOWN_SECONDS` or similar policy setting) and toml execution section.
- [x] AC-04: Unit tests verify extended cooldown for uncredited/exhausted providers, ensuring other healthy providers are chosen without hitting dead accounts on every request.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
