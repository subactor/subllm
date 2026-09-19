# SUBLLM-LLM-EXECUTION: LLM execution failed

## Error DSL

```log-error-dsl
{"category":"DEPENDENCY","causes":["The private upstream response or transport outcome identifies this failure class.","Root cause needs examination of the correlated request and response."],"code":"SUBLLM-LLM-EXECUTION","doNot":["Do not expose credentials or private messages in public logs.","Do not automatically retry MCP tools whose side effects are unknown."],"meaning":"LLM execution failed. This classification is observed; the root cause is not inferred.","owner":"service:subllm","relatedEventTypes":["error_raised"],"remediation":["Inspect the provider attempt code and configured route; the root cause may still be unknown."],"schema":"wellmanifest.logs/error/v1","severity":"ERROR","title":"LLM execution failed","verification":["Inspect the correlated interaction and confirm the documented failure class.","Run python -m pytest -q tests/test_gateway.py before publication."],"version":1}
```

## Situation

LLM execution failed.

## Meaning

Use the private interaction link to distinguish observed facts from possible causes.

## Safe resolution

Inspect the provider attempt code and configured route; the root cause may still be unknown.

## Verification

Run the verification commands in the definition and read back a fresh interaction.

## Do not

Do not publish private payloads or blindly repeat an MCP operation after a lost response.

## Related events

The operational event is error_raised; correlate it with subllm.interaction_started.
