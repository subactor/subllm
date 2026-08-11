# Decisions

## 2026-08-11 — One package, no secrets

The `subllm` package owns provider endpoints, provider-specific model IDs,
application/function route membership and priority. Consumers own prompts,
response validation, budgets and credentials. This keeps policy centralized
without turning the package into a secret store or granting it mutation
authority.

The distribution is named `subactor-subllm`, while the import remains
`subllm`, because the unscoped distribution name is already occupied.

