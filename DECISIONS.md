# Decisions

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
