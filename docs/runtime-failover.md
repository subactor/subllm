# Runtime provider failover

This document defines the execution contract of `subllm.complete()`. Route
membership remains static policy in `src/subllm/policy.py`; runtime health can
only reorder or advance through candidates already declared for the exact
application/function pair.

## Execution sequence

1. Load and validate the complete `subllm.toml` policy.
2. Resolve route candidates, provider enablement and credentials.
3. Move providers in active cooldown behind healthy providers while preserving
   policy order inside both groups.
4. Start one request. Its timeout is the smaller of the remaining total caller
   budget and `attempt_timeout_seconds`.
5. Return the first successful response. If the response was slow, return it
   normally and degrade that provider only for following calls.
6. On a retryable failure, record a secret-free attempt receipt and advance,
   subject to `max_attempts` and the remaining total budget.
7. When no candidate succeeds, raise `CompletionError` containing only the
   application/function and bounded provider/model outcome labels.

The executor is sequential. It never sends speculative parallel copies of a
prompt.

## Failure classification

| Observation | Outcome label | Action in current call | Health scope |
| --- | --- | --- | --- |
| Local attempt timeout | `timeout` | advance | provider |
| Connection, DNS, TLS or socket failure | `transport_error` | advance | provider |
| Cursor SDK failure or missing runtime | `provider_unavailable` | advance | provider |
| HTTP 401 or 403 | `http_401` / `http_403` | advance | provider |
| HTTP 408, 409, 425 or 429 | `http_<status>` | advance | provider |
| HTTP 5xx | `http_<status>` | advance | provider |
| HTTP 404 wire model | `model_unavailable` | advance | model; another declared model on the same provider may run |
| Invalid envelope, empty content or malformed completion | `invalid_response` | advance | model |
| HTTP 400 or another caller/request 4xx | none | fail closed immediately | none |
| Successful response below slow threshold | `success` | return and mark healthy | provider |
| Successful response at/above slow threshold | `success` | return and start cooldown for future calls | provider |

A provider-level failure skips any later model candidate using the same
provider during that call. This prevents repeating a connection or account
failure against a second model endpoint. Model-level failures leave another
declared model on that provider eligible.

## Time and attempt budgets

```toml
[execution]
failover_enabled = true
attempt_timeout_seconds = 12.0
slow_response_seconds = 10.0
cooldown_seconds = 60.0
failure_threshold = 1
max_attempts = 6
```

`timeout_seconds` on `complete()` is the total operation budget. For example,
with a 30-second total and a 12-second attempt limit, a stalled first provider
leaves roughly 18 seconds for later candidates. Routing and Python overhead are
also charged to the total budget.

`failure_threshold` controls how many consecutive failures are needed before a
provider enters cooldown. A fast success resets its failure count. Cooldown
expiry restores the original policy order automatically.

Schema v2 policy files remain readable and receive the built-in execution
defaults. New policy files should use schema v3 and declare the complete
`[execution]` table. Partial or out-of-range execution settings fail closed.

## Receipts and inspection

```python
from subllm import complete, provider_health

result = complete(
    "validator-agent",
    "patch-review",
    [{"role": "user", "content": "Review this bounded patch"}],
    timeout_seconds=30,
    response_format={"type": "json_object"},
)

for attempt in result.attempts:
    print(attempt.provider, attempt.model, attempt.outcome, attempt.duration_ms)

for health in provider_health():
    print(
        health.provider,
        health.status,
        health.consecutive_failures,
        health.cooldown_remaining_seconds,
        health.last_latency_ms,
        health.reason,
    )
```

Attempt and health receipts contain no credentials, request headers, messages,
response content or provider exception bodies. Health is protected by a
process-local lock, is not persisted and is not shared across workers.

`reset_provider_health()` clears the local projection. It is intended for
tests or an explicit operator recovery action, not as a normal request step.

## Cost and mutation boundary

Closing a local HTTP connection does not prove that the remote provider stopped
generation. The timed-out attempt and the successful fallback may both be
billed. Sequential execution limits this risk but cannot provide exactly-once
billing across independent providers.

Automatic failover applies to chat completion through `complete()`.
`execute_code_edit()` and `subllm-code-edit` remain single-attempt because an
interrupted Aider process may already have changed files. Callers must inspect
the worktree before deciding whether such a mutation is safe to repeat.

Set `failover_enabled = false` to execute only the first credential-valid route
with the caller's total timeout. Pure `resolve()` and `available_routes()` never
perform network calls or consult runtime health.
