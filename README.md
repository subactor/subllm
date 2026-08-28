# subllm

`subllm` is the single Python source of truth for Subactor LLM providers,
models, application/function routes and their priorities. The repository name
and import package are `subllm`; the distribution is named
`subactor-subllm` because the unscoped `subllm` distribution name is already in
use.

The repository never tracks credentials. For local development, all SubLLM
consumers in one sibling-project workspace can read provider keys from the
single ignored `subllm/.env` file. In CI and deployments, process environment
variables or a credential vault remain the source and override that file.

## Policy

LLM strategies are assigned by **API-key source** (ADOPT
`wellmanifest/policy-dsl` profile `llm-credential` and
`wellmanifest/env-dsl` `subllm-credential-strategies.env`):

| Credential | Provider | Transport | Default model |
| --- | --- | --- | --- |
| `CURSOR_API_KEY` | `cursor` | Cursor SDK | `gpt-5.6-sol` |
| `ZAI_API_KEY` | `zai` | OpenAI-compatible | `glm-5.3` |
| `OPENROUTER_API_KEY` | `openrouter` | OpenAI-compatible | `glm-5.2` |

`gpt-5.6-sol` is Cursor-only. OpenRouter never claims Sol as
`openai/gpt-5.6-sol`. Missing keys fail closed for that strategy; routes then
continue with later candidates.

Koru is intentionally stricter than the shared default route. Its
`planning-assistant` and `queue-executor` routes allow only Cursor
`grok-4.6` with `effort=xhigh` and `fast=false`; they do not fall back to
OpenRouter, Z.AI, Sol, or a different Cursor preset.

Gemini 3.1 Pro Preview is blocked in the catalog. Provider, model, application
and route definitions live in `src/subllm/policy.py`. See
[`docs/credential-strategies.md`](docs/credential-strategies.md).

Direct Z.AI defaults to `glm-5.3` for every routed application. When Z.AI is
unavailable, role-specific OpenRouter candidates are:

| Consumer route | OpenRouter fallback |
| --- | --- |
| `repair-agent/repair-plan` | `z-ai/glm-5.3-flash` |
| `validator-agent/patch-review` | `z-ai/glm-5.3` |
| `validator-agent/direct-pr-review` | `z-ai/glm-5.3` |
| `onedev-agent/code-edit` (host coding-agent) | `z-ai/glm-5.3` |

`available_routes()` returns these candidates after direct Z.AI. Consumers
performing requests must advance to the next returned route only for a bounded
connectivity/provider failure; SubLLM policy resolution itself does not replay
a paid request.

## Application identity in provider logs

Every application has one stable ID plus an operator-controlled display name
and public attribution URL in [`subllm.toml`](subllm.toml):

```toml
[applications.doctor-agent]
name = "doctor-agent"
url = "https://github.com/subactor/doctor-agent"
```

OpenRouter requests carry the URL in `HTTP-Referer`, the configured name in
`X-OpenRouter-Title`, and the stable application ID in `user`. Z.AI requests
carry the stable ID in `user_id`. Native HTTP and SubLLM-managed LiteLLM calls
also carry a unique `request_id` prefixed with the application and function.
These values contain no credential or end-user personal data.

`ResolvedRoute.litellm_kwargs()` adds the provider-specific fields for
OpenAI-compatible transports. Cursor routes use `cursor_sdk_kwargs()` instead.

## Provider priority and default models

Edit the tracked [`subllm.toml`](subllm.toml) file:

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

Lower priority wins. Set `enabled = false` to remove a provider from every
route. Sibling projects discover this file automatically. Set
`SUBLLM_POLICY_FILE` for another layout.

## Fallback chain

`SUBLLM_PROVIDER_ORDER` is a comma-separated allowlist:
`cursor`, `zai`, `openrouter`. Empty or unset uses the default:

- `cursor,zai,openrouter` when `CURSOR_API_KEY` is set,
- `zai,openrouter` when it is absent.

Unknown names fail closed. `resolve()` returns `cursor` when that candidate
wins and the Cursor key is valid.

Provider order and role model selection are separate: `SUBLLM_PROVIDER_ORDER`
selects the provider sequence, while route membership above selects the model
used through OpenRouter.

## One local credential file

```bash
cp .env.example .env
chmod 600 .env
```

```dotenv
ZAI_API_KEY=YOUR_API_KEY_ID.YOUR_SIGNATURE_SECRET
OPENROUTER_API_KEY=
CURSOR_API_KEY=
SUBLLM_PROVIDER_ORDER=
```

## Python API

```python
from subllm import resolve

route = resolve("repair-agent", "repair-plan")
# wellmanifest/webpage site UX judgment:
# route = resolve("platform", "site-audit")
# strict KiCad EDA compilation:
# route = resolve("twinstudio", "eda-nl2dsl")
if route.provider == "cursor":
    sdk = route.cursor_sdk_kwargs()
else:
    result = completion(**route.litellm_kwargs(), messages=[...])
```

## CLI

```bash
subllm check
subllm providers
subllm resolve doctor-agent repair-proposal --configured
subllm resolve onedev-agent code-edit --provider openrouter --field litellm-model
subllm poa inspect poa://subactor.subllm/process/list-routes/v1
subllm serve --host 127.0.0.1 --port 8788
```

CLI, shell and HTTP share one POA CQRS/ES bus. See [`docs/poa-api.md`](docs/poa-api.md).

## Development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
./scripts/verify
```

See `docs/architecture.md` and `docs/operations.md`.
