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
| Command | `subllm://local/policy/command/edit-process` | proposal planned, started, completed, verified |

Events and receipts never include credential values, raw prompts or shell
strings. `host_shell` and `arbitrary_executable` stay false.

## Governed process DSL editing

An editor first obtains a structured edit list through the centrally routed
`skills-agent/process-editor` LLM function. It then sends the source process,
its exact canonical SHA-256 and those edits to `/v1/commands` with
`process_uri=subllm://local/policy/command/edit-process`.

The URI accepts only `replace` operations listed in the source process's
`decision_policy.llm_editor.editable_paths`. Process identity, required inputs,
allowed actions, artifacts, deterministic controls, editor authority and
publication gates are protected even if an untrusted document tries to add
them to the editable list. A stale base, duplicate path, type change, no-op or
secret-bearing payload fails before an event is appended.

The result is `subllm.process-edit-proposal/v1` with base and candidate digests,
the candidate DSL, an event trail and a terminal receipt. It is not a file
write, grant or publication. The owning registry must validate its schema and
obtain independent validation before publishing the candidate.

The process catalog exporter is Python (`subllm.poa.catalog_document`).
`policy/adopted/poa/process-catalog.json` is the modularity facade.
