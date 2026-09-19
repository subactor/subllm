# SUBLLM-UPSTREAM-TIMEOUT: Upstream did not finish before the deadline

## Error DSL

```log-error-dsl
{"category":"TRANSPORT","causes":["The private upstream response or transport outcome identifies this failure class.","Root cause needs examination of the correlated request and response."],"code":"SUBLLM-UPSTREAM-TIMEOUT","doNot":["Do not expose credentials or private messages in public logs.","Do not automatically retry MCP tools whose side effects are unknown."],"meaning":"Upstream did not finish before the deadline. This classification is observed; the root cause is not inferred.","owner":"service:subllm","relatedEventTypes":["error_raised"],"remediation":["Inspect server load and timeout. Check side effects before retrying a tool."],"schema":"wellmanifest.logs/error/v1","severity":"ERROR","title":"Upstream did not finish before the deadline","verification":["Inspect the correlated interaction and confirm the documented failure class.","Run python -m pytest -q tests/test_gateway.py before publication."],"version":1}
```

## Situation

Upstream did not finish before the deadline.

## Meaning

Use the private interaction link to distinguish observed facts from possible causes.

## Safe resolution

Inspect server load and timeout. Check side effects before retrying a tool.

## Verification

Run the verification commands in the definition and read back a fresh interaction.

## Do not

Do not publish private payloads or blindly repeat an MCP operation after a lost response.

## Related events

The operational event is error_raised; correlate it with subllm.interaction_started.
