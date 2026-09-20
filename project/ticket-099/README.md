# Ticket 099: Support dynamic custom OpenAI-compatible providers in subllm.toml

- **ID**: ticket-099
- **Owner**: unresolved:human
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Created**: 2026-09-20

## Goal and scope

SubLLM hardcodes known providers in `src/subllm/policy.py` (`PROVIDERS` mapping). Introducing a new or local OpenAI-compatible endpoint (e.g. custom proxies, internal gateways, Ollama, vLLM, or LMStudio) previously required modifying code or recompiling the package.

This ticket adds dynamic custom provider configuration via `[custom_providers.<id>]` sections in `subllm.toml`.
Features include:
- Endpoint configuration: `base_url`, `api_key_env`, `priority`, `routes`, `models` list.
- Dynamic registration into `PROVIDERS`, `MODELS`, and `ORDERABLE_PROVIDER_IDS`.
- Support for keyless endpoints (`api_key_env = ""` or missing env var when keyless) without sending empty/dummy Authorization headers.
- Route candidate resolution and priority-ordered provider traversal.
- Strict security validation: HTTPS for remote endpoints, HTTP allowed only for localhost/loopback, prohibition of credentials and queries in `base_url`.

## Acceptance criteria

- [x] AC-01: `[custom_providers.<id>]` sections can be declared in `subllm.toml` with `base_url`, `models`, `priority`, and optional `api_key_env`/`routes`.
- [x] AC-02: Policy catalog dynamically registers custom providers and models into `PROVIDERS`, `MODELS`, and orderable provider IDs.
- [x] AC-03: Security validations enforce safe URLs (HTTPS or localhost HTTP, no embedded credentials or query parameters) and unique priorities.
- [x] AC-04: Resolver injects custom providers into requested routes based on modality, priority, and route configuration.
- [x] AC-05: Worker supports keyless requests without Authorization headers when `api_key_env` is omitted or empty.
- [x] AC-06: Comprehensive unit tests verify loading, validation, fallback, routing, keyless execution, and error handling.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
