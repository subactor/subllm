# Decisions

## 2026-08-28 — Role-specific GLM 5.3 OpenRouter fallback

Keep direct Z.AI `glm-5.3` ahead of OpenRouter. When a consumer advances after
a bounded Z.AI connectivity/provider failure, Repair uses OpenRouter
`z-ai/glm-5.3-flash`; Validator and the host coding-agent's canonical
`onedev-agent/code-edit` route use OpenRouter `z-ai/glm-5.3`.

The model choice follows the current full benchmark: Flash qualified for
Repair at the lowest cost, while full GLM 5.3 remains the requested coding and
review fallback. Benchmark transport compatibility remains consumer-owned.
`available_routes()` exposes the ordered alternatives; policy resolution does
not automatically replay paid requests.

## 2026-08-11 — One package, no secrets

The `subllm` package owns provider endpoints, provider-specific model IDs,
application/function route membership and priority. Consumers own prompts,
response validation, budgets and credentials. This keeps policy centralized
without turning the package into a secret store or granting it mutation
authority.

The distribution is named `subactor-subllm`, while the import remains
`subllm`, because the unscoped distribution name is already occupied.

## 2026-08-12 — Editable operator policy

Provider enablement, numeric priority, default logical models and application
display identity live in the tracked root `subllm.toml`. Catalog membership
and application/function route membership remain versioned Python code. The
strict loader rejects incomplete provider or application sets, conflicting
priorities, forbidden models and unsafe attribution URLs.

## 2026-08-12 — Provider-visible application identity

The application table key is a stable machine ID. OpenRouter receives it as
`user` together with the official URL/title attribution headers. Z.AI receives
it as `user_id`; native HTTP and managed LiteLLM calls also receive a unique
application/function-prefixed `request_id`. Identity fields are public
operational metadata and must never contain secrets or personal data.

Provider ordering is a pre-request decision. The library does not
automatically replay a failed paid request through another provider.

## 2026-08-12 — Z.AI GLM Coding Plan endpoint

The direct Z.AI provider uses `https://api.z.ai/api/coding/paas/v4`. A live
probe authenticated the configured key, returned HTTP 200 and identified the
served model as `glm-5.2`; the general endpoint instead returned provider code
1113 because the account has no separate pay-as-you-go balance. Z.AI keys must
contain exactly one `API Key ID.signature secret` separator so an accidentally
duplicated ID fails before a request and permits pre-request OpenRouter
selection.

## 2026-08-15 — Cursor API key enters the shared credential file

`CURSOR_API_KEY` is the name documented by the Cursor SDK. SubLLM accepts it
in the ignored workspace `.env` and exposes it through the same loader used
for Z.AI and OpenRouter.

`SUBLLM_PROVIDER_ORDER` is the operator-controlled fallback chain. When the
Cursor key is present the default is `cursor,zai,openrouter`. When it is
absent the default stays `zai,openrouter`. An explicit list overrides the
default and unknown ids fail closed.

## 2026-08-16 — Assign LLMs by API-key source (revert OpenRouter Sol)

Cursor Sol (`gpt-5.6-sol`) belongs to the Cursor credential strategy
(`CURSOR_API_KEY` → provider `cursor` → transport `cursor-sdk`). It must not
be published as an OpenRouter wire id (`openai/gpt-5.6-sol`).

Fleet defaults:

| Credential | Provider | Priority | Default model |
| --- | --- | --- | --- |
| `CURSOR_API_KEY` | `cursor` | 0 | `gpt-5.6-sol` (peer `grok-4.6` at +5) |
| `ZAI_API_KEY` | `zai` | 10 | `glm-5.2` |
| `OPENROUTER_API_KEY` | `openrouter` | 20 | `glm-5.2` |

Cursor SDK slugs (live `Cursor.models.list()`): prefer **`gpt-5.6-sol`**,
then **`grok-4.6`**. `resolve()` returns Sol when the Cursor key is valid;
Grok remains an allowlisted cursor-sdk candidate on the same credential.

`resolve()` returns `cursor` when the route lists that candidate and the
Cursor key is valid. Callers use `cursor_sdk_kwargs()`; `litellm_kwargs()`
fails closed for Cursor SDK transport. Standards live in
`wellmanifest/policy-dsl` profile `llm-credential` and
`wellmanifest/env-dsl` `subllm-credential-strategies.env`; this repo ADOPTs
projections under `policy/adopted/`.

Leave `SUBLLM_PROVIDER_ORDER` empty when operator priorities in `subllm.toml`
should control selection. An explicit order rewrites priorities as
`index * 10 + offset` and must stay collision-free with route offsets.

## 2026-08-19 — POA CQRS/ES invoker, policy library unchanged

`resolve()` remains the single exporter of route policy. The new invoker
ADOPTs Process-Oriented Architecture: closed process refs, query/command
URIs, grants bound to a plan hash, an event journal and receipts.

Placement: `home=subactor`, `shape=both`, `runtimeOwner=subactor`.
`runtime_service` does not HOME wellmanifest. CLI, shell and `subllm serve`
share `PolicyBus`. Queries are projections; they must not append events.
Commands may write the local ignored credential file or persist a dry plan.
Events never include credential values. Host shell and arbitrary executables
stay false.
