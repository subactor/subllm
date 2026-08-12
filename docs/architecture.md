# Architecture

## Boundary

`subllm` is a policy library. It does not execute shell commands, access a
credential vault, persist conversations, decide mutations or validate an
agent's domain-specific response.

The library owns four immutable catalogs:

- providers: API base, credential environment name and transport metadata,
- models: logical identity and exact provider-specific model names,
- applications: stable identity and attribution URL,
- routes: ordered candidates for one application/function pair.

For a normal local call, resolution merges the ignored workspace
`subllm/.env` with the process environment. The process environment has higher
precedence, so CI and deployment secret injection stay authoritative. A caller
can instead supply an explicit environment mapping or provider credentials;
an explicit mapping is hermetic and disables local-file discovery.

Only known provider credential names are loaded. The shared file must be a
regular non-symlink file with POSIX mode `0600`. Resolution selects only
candidates whose credential passes the provider's shape check. The selected
value is held in a `repr=False` field and is omitted from public serialization
and CLI output.

## Flow

```text
application + function       subllm/.env < process environment
          |
          v
central route policy -- ordered candidates --> credential availability
          |                                      |
          +--------------------------------------+
                          |
                          v
               resolved provider/model/base
                          |
                +---------+----------+
                |                    |
                v                    v
           LiteLLM kwargs      native HTTP/Aider
```

## Provider failover

Policy ordering and runtime retries are separate. `resolve()` chooses the first
configured candidate. `available_routes()` returns every configured candidate
in priority order for a caller that implements bounded provider failover.
Subllm never retries a paid request by itself, avoiding duplicate side effects
and hidden cost.

## Model safety

Routes list allowed logical models explicitly. A provider may expose the same
logical model under a different wire name. Forbidden models remain in the
catalog only so validation can reject them deterministically; no route may
reference one.
