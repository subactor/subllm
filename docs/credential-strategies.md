# How to force a model given a key source

SubLLM assigns strategies by **credential source**, not by pinning Cursor Sol
onto OpenRouter. Standards HOME: `wellmanifest/{policy-dsl,env-dsl}` profile
`llm-credential`. Runtime HOME: this repository.

| Credential | Strategy | Transport | Default model | Notes |
| --- | --- | --- | --- | --- |
| `CURSOR_API_KEY` | `cursor` | Cursor SDK | `gpt-5.6-sol` | Fallback peer: `grok-4.6`. Never OpenRouter wire ids |
| `ZAI_API_KEY` | `zai` | OpenAI-compatible | `glm-5.3` | Coding Plan base URL |
| `OPENROUTER_API_KEY` | `openrouter` | OpenAI-compatible | `glm-5.2` | Allowlisted OpenRouter models only |

Cursor fallback order (same credential): **`gpt-5.6-sol` then `grok-4.6`**.
Exact Cursor SDK slugs confirmed via `Cursor.models.list()`.

The OpenRouter strategy retains `glm-5.2` as its operator default, but
role-specific failover routes pin benchmark-qualified models: Repair uses
`glm-5.3`; Validator routes use `glm-5.3-flash`; the host coding-agent route
uses `glm-5.3`.

## Force Cursor Sol

1. Set a real `CURSOR_API_KEY` in `subllm/.env` or the process environment.
2. Leave `SUBLLM_PROVIDER_ORDER` empty (toml priorities) or set
   `cursor,zai,openrouter`.
3. Call `resolve(application, function)` — when the route includes the Cursor
   candidate and Cursor wins the configured order, the result has `provider=cursor`,
   `transport=cursor-sdk`, `wire_model=gpt-5.6-sol`.
4. Use `route.cursor_sdk_kwargs()` with `@cursor/sdk`; do **not** call
   `litellm_kwargs()` for cursor.
5. For Grok 4.6 on Cursor, take the second cursor candidate from
   `available_routes()` / `configured_routes()` (`wire_model=grok-4.6`).
   `resolve()` keeps Sol as the default.

## Force Z.AI or OpenRouter

- Missing `CURSOR_API_KEY` skips the cursor candidate (fail-closed for that
  strategy) and continues with `zai` then `openrouter`.
- Set only `OPENROUTER_API_KEY` to force OpenRouter; Sol is not available on
  that wire.
- Explicit `SUBLLM_PROVIDER_ORDER=openrouter,zai` reorders LiteLLM candidates
  and may omit `cursor`.
- Runtime health can temporarily move a degraded provider behind a healthy
  provider, but it never adds a model absent from the route. Use
  `failover_enabled=false` when exact first-candidate execution is required.

`resolve()` is deterministic and does not consult runtime health.
`complete()` applies the runtime behavior described in
[`runtime-failover.md`](runtime-failover.md).

## Projections

Tracked copies of the adopted SSOT live under `policy/adopted/`:

- `credential-strategies.env` — Env DSL constants (no secrets)
- `strategy-catalog.json` — closed strategy catalog

Validate packs in wellmanifest, then refresh these copies when the catalog
changes.
