# SubLLM operator guide

This guide describes the effective local and deployed configuration for every
Python application that uses `subllm`. It contains no credential values.

## Sources of truth

| Concern | Canonical location | Tracked by Git |
| --- | --- | --- |
| Credential → strategy catalog (standards) | `wellmanifest/policy-dsl` `profiles/llm-credential` + `wellmanifest/env-dsl` example | Yes |
| Adopted projections | [`policy/adopted/`](../policy/adopted/) | Yes |
| Provider enabled state, priority and default model | [`subllm/subllm.toml`](../subllm.toml) | Yes |
| Application display name and attribution URL | [`subllm/subllm.toml`](../subllm.toml) | Yes |
| Provider/model catalog and routes | `subllm/src/subllm/policy.py` | Yes |
| Local credentials | `subllm/.env` | No; mode `0600` |
| CI/deployment credentials | Process environment or vault | No |

How to force a model given a key source:
[`docs/credential-strategies.md`](credential-strategies.md).

## Provider selection

```toml
[providers.cursor]
enabled = true
priority = 0
default_model = "gpt-5.6-sol"

[providers.zai]
enabled = true
priority = 10
default_model = "glm-5.3"

[providers.openrouter]
enabled = true
priority = 20
default_model = "glm-5.2"
```

Lower numeric priority wins. Cursor Sol is never an OpenRouter wire id.
`SUBLLM_PROVIDER_ORDER` defaults to `cursor,zai,openrouter` when
`CURSOR_API_KEY` is set, otherwise `zai,openrouter`.

Selection:

1. load and validate the complete policy;
2. remove disabled providers;
3. sort candidates by effective priority;
4. remove candidates without a valid credential;
5. return the first remaining route.

## Application names and provider logs

| Provider | Field | Value |
| --- | --- | --- |
| OpenRouter | `HTTP-Referer` / `X-OpenRouter-Title` / `user` | URL, name, stable ID |
| Z.AI | `user_id` / `request_id` | stable ID / unique id |
| Cursor SDK | `wire_model` via `cursor_sdk_kwargs()` | `gpt-5.6-sol` |

## Credentials

```bash
cd /home/tom/github/subactor/subllm
cp -n .env.example .env
chmod 0600 .env
```

```dotenv
ZAI_API_KEY=YOUR_API_KEY_ID.YOUR_SIGNATURE_SECRET
OPENROUTER_API_KEY=
CURSOR_API_KEY=
SUBLLM_PROVIDER_ORDER=
```

## Safe inspection

```bash
subllm check
subllm providers
subllm resolve doctor-agent repair-proposal --configured
subllm poa catalog
subllm serve --host 127.0.0.1 --port 8788
python -m pytest -q
```

The localhost API is documented in [`poa-api.md`](poa-api.md). Bind only
loopback. Queries do not mutate the journal.
