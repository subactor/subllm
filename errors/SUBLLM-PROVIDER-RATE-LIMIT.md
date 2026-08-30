# SUBLLM-PROVIDER-RATE-LIMIT: Provider rate limit rejected an attempt

## Error DSL

```log-error-dsl
{"category":"RESOURCE","causes":["The selected provider returned HTTP 429 for the bounded completion attempt"],"code":"SUBLLM-PROVIDER-RATE-LIMIT","doNot":["Do not log response bodies, credentials or provider tokens","Do not add unbounded retries or bypass the declared route membership"],"meaning":"One provider refused the attempt because its current quota or request-rate budget was unavailable; policy may continue to another declared candidate.","owner":"service:subllm-runtime","relatedEventTypes":["error_raised","remediation_completed"],"remediation":["Allow bounded failover to another declared candidate when the operation is replay-safe","Otherwise wait for the provider budget to recover and retry within operator-owned limits"],"schema":"wellmanifest.logs/error/v1","severity":"WARNING","title":"Provider rate limit rejected an attempt","verification":["Run the deterministic HTTP 429 failover regression and confirm the successful response retains this attempt code"],"version":1}
```

## Situation

A selected provider returned HTTP 429 during a bounded completion attempt.

## Meaning

That provider's current request or quota budget was unavailable. The attempt
receipt carries this stable code, and policy may continue only to another
candidate already declared for the exact application/function route.

## Safe resolution

Allow bounded failover when the operation is replay-safe. Otherwise wait for
the provider budget to recover, then retry within the operator-owned attempt
and total-time limits.

## Verification

Run the HTTP 429 regression in `tests/test_client.py` and confirm the successful
fallback response retains this code on its failed provider attempt.

## Do not

Do not log provider bodies or credentials, create unbounded retries, or bypass
the declared route membership.

## Related events

Use `error_raised` for the rejected attempt and `remediation_completed` after a
declared fallback or later retry succeeds.
