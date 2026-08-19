# subllm agent instructions

- HOME is `subactor`. Shape is `both` (policy library + runtime invoker).
  ADOPT `wellmanifest/poa`, `wellmanifest/env-dsl`, `wellmanifest/modularity`,
  `wellmanifest/new-project` and `wellmanifest/policy-dsl`. Do not HOME those
  packs. Tickets live in `project/`.
- Keep provider/model/application catalogs and route membership in
  `src/subllm/policy.py`. Keep operator-controlled provider enablement,
  priority, default models and application display identity in the root
  `subllm.toml`; consumers must not grow private copies.
- CLI, shell and localhost HTTP must use `subllm.poa.PolicyBus`. Queries
  never append events. Commands append secret-free `poa.event/v1` records.
  Unknown process URIs fail closed. Do not add a generic shell adapter.
- ADOPT `wellmanifest/policy-dsl` profile `llm-credential` and
  `wellmanifest/env-dsl` `subllm-credential-strategies.env`; refresh
  `policy/adopted/` when those catalogs change. Never pin Cursor Sol on
  OpenRouter wire ids.
- Never commit API keys, key IDs, secret fragments, tokens or `.env` files. The ignored local
  `subllm/.env` is the workspace credential source and must stay mode `0600`. Extra SDK names
  such as `CURSOR_API_KEY` belong in that file, not in tracked docs.
- A new provider needs credential-shape tests and a fixed HTTPS API base.
- A new route needs an exact application/function pair and deterministic
  priority ordering. `SUBLLM_PROVIDER_ORDER` is a comma-separated allowlist
  (`cursor,zai,openrouter`); unknown names fail closed.
- Never silently fall back to a model that the route does not list.
- Run `./scripts/verify` before completing a change.
