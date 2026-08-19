# SubLLM POA API

HOME is `subactor`. Shape is `both`: the Python catalogs stay the policy
library; CLI, shell and localhost HTTP are one runtime invoker. The invoker
ADOPTs `wellmanifest/poa`, `wellmanifest/env-dsl`, `wellmanifest/modularity`
and `wellmanifest/new-project`. It does not HOME those packs.

## Surfaces

All three surfaces use `PolicyBus`. Queries never append events. Commands
append `poa.event/v1` records and a terminal `poa.receipt/v1`.

| Surface | Entry |
| --- | --- |
| Library | `resolve()`, `configured_route()`, `validate_policy()` |
| CLI / shell | `subllm check\|list\|resolve` and `subllm poa …` |
| HTTP | `subllm serve --host 127.0.0.1 --port 8788` |

```bash
subllm poa catalog
subllm poa inspect poa://subactor.subllm/process/list-routes/v1
subllm poa plan poa://subactor.subllm/process/configured-route/v1 --application doctor-agent --function repair-proposal
subllm serve --host 127.0.0.1 --port 8788
```

```bash
curl -sS http://127.0.0.1:8788/health
curl -sS http://127.0.0.1:8788/v1/processes
curl -sS -X POST http://127.0.0.1:8788/v1/queries \
  -H 'Content-Type: application/json' \
  -d '{"schema":"subllm.query/v1","process_uri":"subllm://local/policy/query/validate"}'
```

Bind addresses other than loopback are rejected. Host headers outside
`127.0.0.1`, `localhost` and `::1` are rejected. There is no generic shell
adapter.

## Commands versus queries

| Kind | URI example | Event journal |
| --- | --- | --- |
| Query | `subllm://local/policy/query/validate` | must not append |
| Command | `subllm://local/policy/command/create-plan` | planned + receipt |
| Command | `subllm://local/policy/command/import-credentials` | planned, started, completed, verified |

Events and receipts never include credential values, raw prompts or shell
strings. `host_shell` and `arbitrary_executable` stay false.

The process catalog exporter is Python (`subllm.poa.catalog_document`).
`policy/adopted/poa/process-catalog.json` is the modularity facade.
