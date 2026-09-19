---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "unified-proxy",
  "kind": "information",
  "version": 2,
  "title": "Unified LLM and MCP proxy",
  "status": "implemented",
  "owner": "subactor/subllm",
  "created": "2026-09-19",
  "updated": "2026-09-19",
  "review_after": "2026-10-19",
  "source_revision": "9415a037d9933cbd8c5328041d98f1809b5e595b",
  "scope": "repository",
  "affected_repositories": [
    "subactor/subllm"
  ],
  "evidence": [
    "repo://subactor/subllm/tests/test_gateway.py",
    "https://github.com/subactor/subllm/issues/86"
  ]
}
---

# Unified LLM and MCP proxy

<!-- docs:section purpose -->
## Purpose

SubLLM owns one authenticated gateway for policy-routed LLM calls, configured MCP servers and a private conversation history panel. The gateway is an additional entrypoint; the existing policy API, usage MCP and Ollama-compatible proxy remain compatible.

<!-- docs:section scope -->
## Scope

`subllm-gateway --config /private/gateway.toml` defaults to loopback port 8789. `/v1/chat/completions` uses the existing central model/route catalog. `/mcp/<name>` bridges MCP Streamable HTTP to a configured stdio or Streamable HTTP upstream. `/` displays the shared private archive. The caller comes from its bearer credential, never from an untrusted application header. Each client has explicit LLM and MCP grants; only `read_all=true` operators can read other callers' history.

<!-- docs:section evidence -->
## Evidence

The implementation base is `9415a037d9933cbd8c5328041d98f1809b5e595b`. Tests exercise real stdio framing through HTTP, session isolation, tool errors, concurrent writes, midnight completion, unavailable storage, query purity, credential exclusion, response links and the operational hash chain. A local PostgreSQL 16 pilot verified write/readback. These observations do not establish fleet-wide client adoption or protected publication.

The MCP adapter pins SDK 1.26.0 and delegates transport framing to its session manager, verified against the [pinned implementation](https://github.com/modelcontextprotocol/python-sdk/blob/v1.26.0/src/mcp/server/streamable_http_manager.py) and [transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports). Runtime does not fetch those URLs.

The adopted Logs contract is `wellmanifest/logs` revision `8374d5364e5c78ae69806fb60a06aa52cd23d1e3`, contract 0.5.0 SHA-256 `72e16ac823359879e01722e1e3e7017f50524c8cdf54e8eaec9d8802bc804e36`. `.governance/logs/catalog.json` and `policy/adopted/logs/event.schema.json` are checked against that contract by `scripts/check-logs.py`, invoked by `scripts/verify`. Machine runbooks live under `.governance/logs/errors/{CODE}.md` relative to the adopted Logs catalog; they use the Logs schema and section grammar, while this human-facing guide uses Docs. Existing runtime runbooks in the root errors directory retain their historical placement. Operational events carry stable codes, severity, outcome, correlation, timing and remediation references. Private request/response bodies are a separate archive, never `wellmanifest.logs/event/v1` payloads.

<!-- docs:section content -->
## Content

Install the `gateway` extra. Credentials and configuration remain outside Git. An example configuration follows; the named environment variables must exist, and each token must be distinct and at least 32 characters.

```toml
archive_directory = "/home/operator/.local/state/subllm/interactions"
allowed_hosts = ["127.0.0.1:8789", "localhost:8789"]
postgres_dsn_env = "SUBLLM_GATEWAY_DATABASE_URL"
max_sessions_per_server = 16

[clients.operator]
token_env = "SUBLLM_OPERATOR_TOKEN"
llm = true
read_all = true
mcp = ["usage"]

[mcp.usage]
command = "/absolute/path/to/python"
args = ["-m", "subllm.cli", "mcp"]
session_lifetime_seconds = 3600
```

Upstreams declare either `command` with `args`, optional `cwd` and `env_from` (child environment name to gateway environment name), or `url` and `headers_from` (HTTP header name to gateway environment name). URLs cannot embed credentials. The child process only inherits the MCP SDK's minimal default environment plus explicitly mapped values. Environment contents, HTTP credentials and stderr are not copied to public logs.

Stdio-only clients can use `subllm-mcp-proxy --url https://gateway:8789/mcp/usage --token-file /private/client-token --ca-file /private/gateway.crt`. This adapter preserves JSON-RPC messages and reads credentials from a private file; no token appears in the process arguments.

Clients use a bearer token for the LLM API and MCP URL. The panel asks for the operator token and keeps it only in memory. Deep links have the form `/#YYYY-MM-DD/<interaction-id>`, without a token. API detail queries use `/v1/interactions?day=YYYY-MM-DD&id=<interaction-id>` and enforce caller ownership. Lists omit request/response bodies. Filters cover UTC day, kind, status, limit (maximum 500) and `before` timestamp.

With `SUBLLM_GATEWAY_DATABASE_URL`, a single PostgreSQL database contains daily range partitions and transactional event projections. Without it, SQLite creates one private `YYYY-MM-DD.sqlite3` per UTC start day. A call finishing after midnight stays with its start day. Reads do not create database files. `--export-day YYYY-MM-DD --export-to /private/export/YYYY-MM-DD.sqlite3` creates a consistent SQLite snapshot and refuses overwrites. Retention is operator-managed; no automatic deletion is enabled.

The gateway records a request before dispatch and records completion separately. An unfinished row stays `pending`; this is not proof of an active request. Initial archive failure prevents a new upstream dispatch. A final LLM archive failure preserves the paid response, emits a fixed diagnostic and returns `X-SubLLM-Archive-Status: pending`; it never retries the LLM to repair logging. MCP tools are never retried automatically. Notifications and server-to-client requests are captured with their direction, preserving JSON-RPC IDs and capabilities. Sessions belong to individual authenticated clients and have a bounded lifetime.

LLM parent interactions link per-provider attempts through `correlation_id`. The archive includes the selected provider/model, failure class and private response body when the OpenAI-compatible worker can capture it. Credential header values never enter that channel; the worker also removes any exact credential echoed by an upstream. Provider response size bounds still apply. SDK/CLI transports expose their normalized response and available metadata; internal SDK messages not exposed by the client are not claimed as wire capture.

Errors distinguish upstream authentication, limits, timeout, transport, MCP protocol failure, MCP `isError`, interrupted sessions and generic LLM execution failures. The panel labels the observed failure class separately from the unproven root cause and links correlated payloads. Daily operational events use a canonical SHA-256 chain; database transactions serialize concurrent writers. The gateway records reference-only commands through PolicyBus; its private archive query method has no write effects.

For LAN use, bind with an explicit TLS certificate/key, register the actual authority in `allowed_hosts`, and distribute the certificate trust and individual client credentials. PostgreSQL can remain loopback-only; LAN clients connect to the gateway API. [SQLite's deployment guidance](https://www.sqlite.org/whentouse.html) supports choosing a client/server database for many networked writers; this is not a claim that PostgreSQL is always faster. Daily [PostgreSQL partitions](https://www.postgresql.org/docs/current/ddl-partitioning.html) provide storage organization, not separate daily servers.

<!-- docs:section limitations -->
## Limitations

Only calls entering this gateway are captured. Existing Cursor/Codex stdio configurations, OpenCode's direct provider path and external applications require explicit migration; restarting existing sessions is separate from editing their configuration. One server endpoint does not prove universal coverage.

The LLM endpoint supports the current SubLLM text completion contract (`model`, `messages`, `stream`, and route-only `response_format`). Unknown generation parameters are rejected, not silently dropped. Streaming is emitted after the routed completion, as in the existing proxy; this is not live upstream token streaming. Arbitrary tool-calling generation and provider-native APIs outside that contract need additional adapters. MCP HTTP supports the pinned SDK's Streamable HTTP transport, not legacy HTTP+SSE endpoints.

The pilot has no automatic disk retention, crash replay, multi-host deployment failover or durable MCP session resumption. A lost response can follow a tool side effect. Session IDs are isolated by caller; credentials grant the configured server capabilities, so tool permissions still need upstream enforcement. Private payloads can contain user-supplied sensitive text; access and backups must remain private. PostgreSQL credentials need only the gateway's dedicated database, not unrelated application databases.

<!-- docs:section next_actions -->
## Next actions

Run `./scripts/verify` for the default suite and pinned Logs adoption checks. Run `python -m pytest -q integration/test_gateway_postgres.py` separately with `SUBLLM_TEST_POSTGRES_DSN` pointing to a dedicated test database. This integration suite requires that database and fails when the DSN is missing; it never reports an unexecuted database check as successful. Each run creates and removes its own unique schema, verifying concurrent writes, UTC midnight partitioning and SQLite export. Publish via the protected local executor and independent Validator. Deploy a pinned artifact, migrate clients in bounded batches, verify a real read-only MCP call and LLM call from each consumer, and keep coverage gaps visible until observed traffic confirms adoption.
