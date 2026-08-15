# SubLLM operator guide

This guide describes the effective local and deployed configuration for every
Python application that uses `subllm`. It contains no credential values.

## Sources of truth

| Concern | Canonical location | Tracked by Git |
| --- | --- | --- |
| Provider enabled state, priority and default model | [`subllm/subllm.toml`](../subllm.toml) | Yes |
| Application display name and attribution URL | [`subllm/subllm.toml`](../subllm.toml) | Yes |
| Provider/model catalog and application/function route membership | `subllm/src/subllm/policy.py` | Yes |
| Local Z.AI, OpenRouter and Cursor credentials | `subllm/.env` | No; mode `0600` |
| CI/deployment credentials | Process environment or credential vault | No |

Process credentials override the shared local `.env`. `SUBLLM_ENV_FILE` and
`SUBLLM_POLICY_FILE` select explicit files when repositories are not siblings.
An explicit policy path that is missing or invalid fails closed.

## Provider selection

The tracked policy starts with:

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

Lower numeric priority wins. Set `enabled = false` to remove a provider from
every route. Each enabled provider must have a unique priority. The configured
default model must exist, be allowed and be available through that provider.

`SUBLLM_PROVIDER_ORDER` is the high-level fallback chain. Known ids are
`cursor`, `zai` and `openrouter`. The default is `cursor,zai,openrouter`
when `CURSOR_API_KEY` is set and `zai,openrouter` when it is not. An
explicit list overrides that default; unknown names fail closed. `cursor`
is the Cursor SDK backend and is not returned by `resolve()`.

Selection happens before an API request:

1. load and validate the complete policy;
2. remove disabled providers;
3. sort candidates by effective priority;
4. remove candidates without a valid credential;
5. return the first remaining route.

A missing or malformed Z.AI credential therefore allows OpenRouter to be
selected. A timeout or HTTP error after a Z.AI request has started does not
automatically repeat that paid request through OpenRouter. A caller that needs
bounded runtime failover must explicitly iterate `available_routes()` and own
the duplicate-cost and duplicate-side-effect policy.

The fleet uses the Z.AI GLM Coding Plan endpoint
`https://api.z.ai/api/coding/paas/v4`. The same credential can authenticate at
the general endpoint while still receiving provider error `1113` when the
account has a Coding Plan but no pay-as-you-go balance; do not use that result
as evidence that the Coding Plan is unavailable.

## Application names and provider logs

Every route uses a stable application ID. Its display name and public URL are
configured in the same policy file:

```toml
[applications.doctor-agent]
name = "doctor-agent"
url = "https://github.com/subactor/doctor-agent"
```

The table key is the stable machine ID. Changing `name` changes the displayed
OpenRouter title but does not change the route ID or the `user`/`user_id`
value. The URL must use HTTPS and must not contain credentials, a query or a
fragment.

Provider-visible fields are:

| Provider | Field | Value |
| --- | --- | --- |
| OpenRouter | `HTTP-Referer` header | configured application URL |
| OpenRouter | `X-OpenRouter-Title` header | configured application name |
| OpenRouter | `user` request field | stable application ID |
| Z.AI | `user_id` request field | stable application ID |
| Z.AI native HTTP / managed LiteLLM | `request_id` | unique `<application>-<function>-...` identifier |

The OneDev Aider integration passes `user_id=onedev-agent`; Z.AI generates the
request ID for that client. None of these fields may contain credentials,
prompts, email addresses or other personal data.

Current routes are:

| Application ID | Function |
| --- | --- |
| `doctor-agent` | `repair-proposal` |
| `repair-agent` | `repair-plan` |
| `validator-agent` | `patch-review`, `direct-pr-review` |
| `skills-agent` | `developer`, `validator` |
| `onedev-agent` | `code-edit` |
| `platform` | `interactive` |

## Credentials

Create the private local file once from [`.env.example`](../.env.example):

```bash
cd /home/tom/github/subactor/subllm
cp -n .env.example .env
chmod 0600 .env
```

Its accepted names are:

```dotenv
ZAI_API_KEY=YOUR_API_KEY_ID.YOUR_SIGNATURE_SECRET
OPENROUTER_API_KEY=YOUR_OPENROUTER_KEY
CURSOR_API_KEY=
SUBLLM_PROVIDER_ORDER=
```

The Z.AI value must contain exactly one dot: the API Key ID before it and the
signature secret after it. `ID.ID.secret` is malformed. `CURSOR_API_KEY` is
the name documented by the Cursor SDK; mint it from Cursor Dashboard →
Integrations and pass it explicitly to the SDK, or export it in the process
environment. Never commit the file or print its values in diagnostics.

## Safe inspection

These commands do not call a provider:

```bash
subllm check
subllm providers
subllm applications
subllm list
subllm env path
subllm env check
subllm resolve doctor-agent repair-proposal --configured
subllm resolve validator-agent patch-review \
  --configured --provider openrouter --field application-name
```

`subllm providers` and `subllm applications` show the effective source file.
`subllm env check` prints only variable names and configured/missing state.
Without `--configured`, `subllm resolve` also requires a valid credential but
still never prints its value.

After editing `subllm.toml`, run:

```bash
subllm check
python -m pytest -q
```

Host processes reload the policy during route resolution. A container must
have the file mounted at `SUBLLM_POLICY_FILE`; changing the Compose mount or
environment normally requires recreating that service.

## Adding an application or route

Application and route membership remain a versioned code contract. To add
one, update `APPLICATIONS` and `ROUTES` in `src/subllm/policy.py`, add the exact
application table to `subllm.toml`, add attribution/request-field tests, bump
the package version and pin the resulting immutable commit in the consumer.
The strict policy loader rejects missing or unknown application tables.

## Provider references

- [OpenRouter app attribution](https://openrouter.ai/docs/app-attribution)
- [Z.AI chat completion request fields](https://docs.z.ai/api-reference/llm/chat-completion)
