# subllm agent instructions

- Keep provider/model/application catalogs and route membership in
  `src/subllm/policy.py`. Keep operator-controlled provider enablement,
  priority, default models and application display identity in the root
  `subllm.toml`; consumers must not grow private copies.
- Never commit API keys, key IDs, secret fragments, tokens or `.env` files. The ignored local
  `subllm/.env` is the workspace credential source and must stay mode `0600`. Extra SDK names
  such as `CURSOR_API_KEY` belong in that file, not in tracked docs.
- A new provider needs credential-shape tests and a fixed HTTPS API base.
- A new route needs an exact application/function pair and deterministic
  priority ordering. `SUBLLM_PROVIDER_ORDER` is a comma-separated allowlist
  (`cursor,zai,openrouter`); unknown names fail closed.
- Never silently fall back to a model that the route does not list.
- Run `./scripts/verify` before completing a change.
