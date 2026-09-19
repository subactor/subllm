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

Koru planning, queue, reflection and DSL routes use the shared declared
Z.AI → Cursor → OpenRouter chain. Runtime health may temporarily exclude only
cooling candidates already present in each exact route.

Gemini 3.1 Pro Preview is blocked in the catalog. Provider, model, application
and route definitions live in `src/subllm/policy.py`. See
[`docs/credential-strategies.md`](docs/credential-strategies.md).

Direct Z.AI defaults to `glm-5.3` for every routed application. When Z.AI is
unavailable, role-specific OpenRouter candidates are:

| Consumer route | OpenRouter fallback |
| --- | --- |
| `repair-agent/repair-plan` | `z-ai/glm-5.3` |
| `validator-agent/patch-review` | `z-ai/glm-5.3-flash` |
| `validator-agent/direct-pr-review` | `z-ai/glm-5.3-flash` |
| `onedev-agent/code-edit` (host coding-agent) | `z-ai/glm-5.3` |
| `twinstudio/{eda-nl2dsl,eda-firmware-audit,eda-conflict-chat}` | `z-ai/glm-5.3-flash` |
| `autogrammar-nexu/vision` | `z-ai/glm-4.5v` |
| `autogrammar-nlp2cmd/vision` | `z-ai/glm-4.5v` |
| `autogrammar-vql/vision` | `z-ai/glm-4.5v` |
| `autogrammar-imgl/vision` | `z-ai/glm-4.5v` |

Vision routes are a separate modality. They send OpenAI-compatible `image_url`
parts, never use Cursor SDK, and fail closed on a text route, a missing image,
or a `file:` / `http:` image URL. Text routes such as
`autogrammar-nexu/cinema` stay text-only.

`available_routes()` returns these candidates after direct Z.AI.
`subllm.complete()` executes bounded sequential failover across that exact
list. It advances after an attempt timeout, connection failure, provider
authentication/rate/transient HTTP failure, missing wire model or invalid
completion response. A successful response slower than the configured threshold
is returned, but that provider is excluded from following calls during its
cooldown. If every candidate is cooling, the call fails immediately and a later
call restores routes after expiry. Every successful result includes secret-free
`attempts` metadata.

Failover does not issue parallel speculative requests. This avoids knowingly
duplicating paid calls, although a remote provider may still finish and bill a
request after the local connection timeout. Non-retryable request errors such as
HTTP 400 fail closed. Mutable `subllm-code-edit` / Aider execution is never
replayed automatically.

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
priority = 20
default_model = "gpt-5.6-sol"

[providers.zai]
enabled = true
priority = 0
default_model = "glm-5.3"

[providers.openrouter]
enabled = true
priority = 30
default_model = "glm-5.2"
```

Lower priority wins. Set `enabled = false` to remove a provider from every
route. Sibling projects discover this file automatically. Set
`SUBLLM_POLICY_FILE` for another layout.

## Fallback chain

`SUBLLM_PROVIDER_ORDER` is a comma-separated allowlist:
`zai`, `cursor`, `openrouter`. Empty or unset leaves ordering to the priorities
in `subllm.toml`, currently:

- `zai,cursor,openrouter` when all three credentials are valid,
- `zai,openrouter` when it is absent.

Unknown names fail closed. `resolve()` returns `cursor` when that candidate
wins and the Cursor key is valid.

Provider order and role model selection are separate: `SUBLLM_PROVIDER_ORDER`
selects the provider sequence, while route membership above selects the model
used through OpenRouter.

## Runtime resilience

The root [`subllm.toml`](subllm.toml) owns the execution thresholds:

```toml
[execution]
failover_enabled = true
attempt_timeout_seconds = 12.0
slow_response_seconds = 10.0
cooldown_seconds = 60.0
failure_threshold = 1
max_attempts = 6
```

The `timeout_seconds` argument of `complete()` is the total caller budget. Each
provider receives at most `attempt_timeout_seconds` from the remaining budget.
Health is shared across completion processes and self-recovers after cooldown;
it is secret-free routing memory, not durable authority. The default state file
is `${XDG_STATE_HOME:-$HOME/.local/state}/subllm/provider-health.json` and an
absolute `SUBLLM_HEALTH_STATE_FILE` overrides that location. Operators can
inspect `provider_health()` or explicitly clear it with
`reset_provider_health()`.

The full retry classification, ordering algorithm, response receipts and cost
boundary are documented in [`docs/runtime-failover.md`](docs/runtime-failover.md).

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
from subllm import complete, provider_health

result = complete(
    "repair-agent",
    "repair-plan",
    [{"role": "user", "content": "Prepare a repair plan"}],
    timeout_seconds=30,
)
print(result.provider, result.model, result.attempts)
print(provider_health())
```

## CLI

```bash
subllm check
subllm providers
subllm resolve doctor-agent repair-proposal --configured
subllm resolve onedev-agent code-edit --provider openrouter --field litellm-model
subllm poa inspect poa://subactor.subllm/process/list-routes/v1
subllm serve --host 127.0.0.1 --port 8788
subllm proxy --host 127.0.0.1 --port 11435
```

## SubLLM Local Proxy (`subllm proxy` / `subllm-proxy`)

`subllm proxy` runs an OpenAI- and Ollama-compatible HTTP proxy server on `http://127.0.0.1:11435`.
It allows local agents (`koru`, `tillm`, `gillm`, `taskand`, `premesh`), IDEs (Cursor, VSCode Continue, Aider),
and CLI tools to execute paid cloud models (`glm-5.3`, `gpt-5.6-sol`, `deepseek-v4-pro`, `grok-4.6`, `composer-2.5`)
transparently **without client-side credentials or passwords**.

- **Ollama consumers (`tillm`, `gillm`, `ollama` CLI, `aider`):**
  ```bash
  export OLLAMA_HOST=http://127.0.0.1:11435
  ollama run glm-5.3 "Napisz podsumowanie"
  ```
- **OpenAI-compatible consumers (`koru`, `cursor`, `continue.dev`):**
  ```bash
  export OPENAI_API_BASE=http://127.0.0.1:11435/v1
  export OPENAI_API_KEY=subllm-local
  ```
- **Ticket attribution and receipts:**
  Pass `X-Ticket: ticket-NNN` or request model `glm-5.3@ticket-NNN`.
  Execution receipts are automatically written to `~/.subactor/receipts/ticket-NNN--<timestamp>--<provider>.json`.
- **Local Ollama forwarding:**
  Requests for unknown or local GGUF models are transparently forwarded to the local Ollama daemon on `http://127.0.0.1:11434`.

CLI, shell and HTTP share one POA CQRS/ES bus. See [`docs/poa-api.md`](docs/poa-api.md).
The registered `edit-process` command validates LLM-authored process DSL edits
against exact-base and editable-path controls. It returns a proposal and
receipt only; it never changes the process registry or grants execution.

## Development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[test]'
./scripts/verify
```

See `docs/architecture.md`, `docs/operations.md` and
`docs/runtime-failover.md`.

Documentation deliverables follow [AGENTS.md](AGENTS.md) and the [documentation index](docs/README.md).


Local Codex: [integration, configuration and verification](docs/analysis/codex-cli-integration.md).


## API usage dashboard

Run `subllm serve --host 127.0.0.1 --port 8788` and open
<http://127.0.0.1:8788/>. The local panel shows which application/function called
which provider/model, timestamps, success/failure, latency and input/output
tokens. Filter by application, provider, result and time; browse older attempts
or refresh the newest page every five seconds. A shared request ID connects
fallback attempts. Token totals cover only reported usage; missing values are
shown as unknown, including failed attempts that may still incur provider charges.
No price or cost is invented.

Updated SubLLM completion clients write a private SQLite journal at
`~/.local/state/subllm/usage.sqlite3` (or `$XDG_STATE_HOME/subllm/usage.sqlite3`).
Set `SUBLLM_USAGE_DB` to the same absolute path for clients and server to use a
custom journal. Separate OS users or containers require an explicitly shared,
access-controlled location. New database files are mode `0600`. History is
retained until the operator archives/removes the database; there is no automatic
expiry in this version. Back up a running database with SQLite's backup API.

Coverage starts when clients are upgraded and restarted. It includes the Python
`complete()` client and the proxy's catalog-model/registered-route completions.
It does not include direct SDK/HTTP calls outside SubLLM, local Ollama forwarding,
code-edit transports, requests rejected before a provider attempt, or older pinned
runtimes. Proxy clients should supply `X-Subactor-Application` and
`X-Subactor-Function` or use a registered `application/function` model alias.
Without application attribution, proxy traffic is shown as `subactor-proxy`;
caller-declared identity is not authenticated identity.

Only bounded metadata and numeric token counts are stored: no prompts, generated
content, raw exceptions, headers or credentials. A journal failure logs a fixed
warning without changing a completion result or triggering a paid retry. The
panel distinguishes an empty journal from an unavailable/corrupt database.

The same read-only projection is exposed by `GET /v1/usage` and the PolicyBus
query `subllm://local/policy/query/usage`, including through `subllm poa query`.
HTTP filters: `application`, `provider`, `status` (`success`/`error`), `since` and
`until` (timestamps with timezone), `limit` (1–500), and `before` (pagination ID).
Summary totals apply to the whole filtered result, not just the visible page.
Queries never create or append to the journal. Keep this server on loopback;
foreign browser origins are rejected and no permissive CORS is enabled.

Browser acceptance uses synthetic records in an isolated temporary database:
`PYTHONPATH=src python scripts/verify-usage-browser.py` (requires Playwright and
its Chromium installation; `--browser` accepts an existing Chromium executable).
It checks filters, reset, live refresh, desktop/mobile layout and browser errors.


## MCP, NL/DSL and transport telemetry

Version 1.13 adds read-only MCP on the panel's `/mcp` endpoint (Streamable HTTP,
JSON responses) and `subllm mcp` (stdio). Tools: `execute_dsl`, `nl_ask`, and
`describe_grammar`; resource: `schema://current`. Example tool arguments:
`{"command":"usage.list provider=zai application=validator-agent limit=20"}`.
CLI equivalents: `subllm dsl 'usage.list provider=zai'` and
`subllm ask 'pokaż logi z.ai'`. REST equivalents are `POST /api/v1/dsl` with
`command`, `POST /api/v1/query` with `question`, and `GET /api/v1/schema`.
All reads use the same PolicyBus projection and never contact a provider.

This is a bounded read-only interface subset inspired by
[wellmanifest/nl-dsl-llm](https://github.com/wellmanifest/nl-dsl-llm/blob/2040efe37b9eb898350f3fec0285a2d4e69d4e34/spec/NL_DSL_LLM_SPECIFICATION.md),
not a claim of full draft conformance: there is no paid NL fallback or mutation
DSL. Unknown questions and commands fail closed. MCP transport follows the
[2025-06-18 specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports).
Configure MCP clients with `command: subllm`, `args: [mcp]` for stdio, or the
actual panel URL plus `/mcp` for HTTP (this host uses port 18988). Keep it local.

Applications with their own LiteLLM/HTTP transport must report each actual
attempt to `POST /v1/commands`, using process URI
`subllm://local/policy/command/record-usage`, schema `subllm.command/v1`, a
`service:...` subject, a unique `usage.<uuid>` idempotency key, and an `attempt`:
`request_id`, `application`, `function`, `provider`, `model`, `status`
(`success`/`error`), `duration_ms`, and `usage` containing only optional numeric
`input_tokens`/`output_tokens`. Optional `diagnostic_code` is a bounded code,
never a provider message. Unknown fields, content and invalid values are rejected.
Each attempt key is deduplicated persistently. The collector emits a secret-free
POA event for accepted new attempts; query operations remain read-only.

A routing lookup alone does not record usage. Transport adapters must be deployed
and enabled, with `SUBLLM_USAGE_URL` set to the collector's loopback base URL.
Their delivery failures must not alter provider results or trigger paid retries.
Caller-declared application metadata is not an authenticated billing identity.
No old receipt files are automatically imported: historical test fixtures must
never be presented as actual provider traffic.
