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

The initial fleet policy uses the same logical GLM 5.2 model through two
providers:

1. direct Z.AI (`ZAI_API_KEY`, `https://api.z.ai/api/paas/v4`),
2. OpenRouter (`OPENROUTER_API_KEY`, `https://openrouter.ai/api/v1`).

Direct Z.AI is preferred when its complete `API_KEY_ID.signature_secret` value
is present. OpenRouter remains the fallback. A route may explicitly allow
additional models, but there is no global silent fallback to an unrelated
model. Gemini 3.1 Pro Preview is blocked in the catalog.

Provider, model, application and route definitions live only in
`src/subllm/policy.py`.

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
also carry a unique `request_id` prefixed with the application and function,
for example `doctor-agent-repair-proposal-...`. These values contain no
credential or end-user personal data.

`ResolvedRoute.litellm_kwargs()` adds the provider-specific fields
automatically. Direct HTTP clients use `route.provider_request_fields()`.

## Provider priority and default models

Edit the tracked [`subllm.toml`](subllm.toml) file to control both providers:

```toml
[providers.zai]
enabled = true
priority = 10
default_model = "glm-5.2"

[providers.openrouter]
enabled = true
priority = 20
default_model = "glm-5.2"
```

Lower priority wins. Set `enabled = false` to remove a provider from every
route. `default_model` is a logical ID from the model catalog; SubLLM rejects
unknown, forbidden or provider-incompatible values. Explicit additional models
declared by a route remain later candidates and their offsets are added to the
provider priority.

Sibling projects discover this file automatically. Set `SUBLLM_POLICY_FILE`
for another layout. When no file is available, such as an isolated CI install,
the package uses the same built-in defaults shipped with that release.

This ordering controls selection before a request. It does not automatically
repeat a failed paid request through another provider; callers that implement
bounded runtime failover use `available_routes()` in this order.

## One local credential file

Create the private file once in this repository:

```bash
cp .env.example .env
chmod 600 .env
```

Set complete provider values there:

```dotenv
ZAI_API_KEY=YOUR_API_KEY_ID.YOUR_SIGNATURE_SECRET
OPENROUTER_API_KEY=YOUR_OPENROUTER_KEY
```

When an application is a sibling of this repository, `resolve()` discovers
`subllm/.env` automatically. For another layout, set `SUBLLM_ENV_FILE` to an
absolute path or to a path relative to the process working directory. An
explicit process variable wins over the corresponding value in the file.

Only credential variables declared by providers in `policy.py` are accepted.
The file must be a regular, non-symlink file with mode `0600` on POSIX.

## Python API

```python
from subllm import resolve

route = resolve("repair-agent", "repair-plan")
result = completion(
    **route.litellm_kwargs(),
    messages=[{"role": "user", "content": "..."}],
)
```

The resolved credential is excluded from object representations and public
serialization:

```python
route.public_dict()
# {'application': 'repair-agent', 'function': 'repair-plan', ...}
```

For a transport that already owns its credential, resolve policy without
reading the environment:

```python
from subllm import configured_route

route = configured_route("onedev-agent", "code-edit", provider="openrouter")
print(route.litellm_model)
```

## CLI

The CLI prints only public configuration:

```bash
subllm check
subllm list
subllm providers
subllm applications
subllm env path
subllm env check
subllm resolve validator-agent patch-review --configured
subllm resolve onedev-agent code-edit --provider openrouter --field litellm-model
```

Existing local agent files can be imported without printing their values:

```bash
subllm env import ../doctor-agent/.env ../repair-agent/.env --target .env
```

Without `--configured`, `resolve` requires a valid credential for the selected
provider. The CLI reports only configured variable names and never prints a
credential.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
./scripts/verify
```

See `docs/architecture.md` for the trust boundary and migration rules.
See the
[`SubLLM operator guide`](https://github.com/subactor/subllm/blob/main/docs/operations.md)
for the complete provider, application naming, credential and provider-log
runbook.
