# SUBLLM-PROVIDER-CHAIN-EXHAUSTED: Bounded provider chain was exhausted

## Error DSL

```log-error-dsl
{"category":"CHAIN","causes":["Every eligible route candidate failed or the bounded total timeout expired"],"code":"SUBLLM-PROVIDER-CHAIN-EXHAUSTED","doNot":["Do not add an undeclared provider or model to bypass the route policy","Do not replay a mutable code-edit execution automatically"],"meaning":"No declared candidate completed within the operator-owned attempt and total-time bounds, so SubLLM stopped without inventing another route.","owner":"service:subllm-runtime","relatedEventTypes":["error_raised","remediation_completed"],"remediation":["Inspect the secret-free attempt outcomes and provider health receipts","Restore an eligible provider or credential, respect cooldown and retry the original operation only when replay is safe"],"schema":"wellmanifest.logs/error/v1","severity":"ERROR","title":"Bounded provider chain was exhausted","verification":["Run the deterministic exhausted-provider-chain regression test and confirm the raised diagnostic code"],"version":1}
```

## Situation

All eligible candidates failed, or the operator-owned total completion timeout
expired before another bounded attempt could start.

## Meaning

SubLLM stopped at the declared route boundary. It did not invent a provider,
model or retry beyond the execution policy.

## Safe resolution

Inspect the attempt outcomes and process-local provider health receipts.
Restore an eligible dependency or credential, respect its cooldown and retry
only when the original operation is safe to replay.

## Verification

Run the exhausted-chain regression in `tests/test_client.py` and confirm the
raised `CompletionError.diagnostic_code` equals this filename.

## Do not

Do not append an undeclared fallback, retry without a bound, expose raw
provider responses or automatically replay mutable code-edit executions.

## Related events

Use `error_raised` for the terminal chain failure and
`remediation_completed` after a later bounded request succeeds.
