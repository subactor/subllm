# SUBLLM-PROVIDER-UNAVAILABLE: Provider was unavailable for a bounded attempt

## Error DSL

```log-error-dsl
{"category":"DEPENDENCY","causes":["A provider timed out, failed transport, rejected authentication, returned a retryable server status or produced an invalid response"],"code":"SUBLLM-PROVIDER-UNAVAILABLE","doNot":["Do not expose raw provider responses or credentials in the receipt","Do not permanently reorder policy from one transient process-local health observation"],"meaning":"The selected provider could not safely complete this attempt, so SubLLM recorded a secret-free failure and may continue within the declared chain.","owner":"service:subllm-runtime","relatedEventTypes":["error_raised","remediation_completed"],"remediation":["Inspect the attempt outcome and process-local health receipt","Restore provider connectivity or credentials, or let bounded failover select the next declared candidate"],"schema":"wellmanifest.logs/error/v1","severity":"WARNING","title":"Provider was unavailable for a bounded attempt","verification":["Run the deterministic timeout failover regression and confirm the failed attempt carries this code"],"version":1}
```

## Situation

A provider timed out, failed transport, rejected authentication, returned a
retryable server status or produced an invalid completion response.

## Meaning

The selected dependency could not safely complete this attempt. SubLLM records
a secret-free outcome and may continue only within the declared candidate
chain and execution bounds.

## Safe resolution

Inspect the stable attempt outcome and process-local health receipt. Restore
connectivity or credentials, or allow bounded failover to the next declared
candidate.

## Verification

Run the timeout failover regression in `tests/test_client.py` and confirm the
failed attempt carries this code while the successful attempt has no error
code.

## Do not

Do not expose raw provider responses or credentials, and do not make one
transient health observation a permanent policy reorder.

## Related events

Use `error_raised` for the failed attempt and `remediation_completed` after a
declared fallback or later retry succeeds.
