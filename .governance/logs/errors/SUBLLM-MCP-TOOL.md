# SUBLLM-MCP-TOOL: MCP tool returned isError=true

## Error DSL

```log-error-dsl
{"category":"RUNTIME","causes":["The private upstream response or transport outcome identifies this failure class.","Root cause needs examination of the correlated request and response."],"code":"SUBLLM-MCP-TOOL","doNot":["Do not expose credentials or private messages in public logs.","Do not automatically retry MCP tools whose side effects are unknown."],"meaning":"MCP tool returned isError=true. This classification is observed; the root cause is not inferred.","owner":"service:subllm","relatedEventTypes":["error_raised"],"remediation":["Read the tool response and its runbook. Transport success does not imply tool success."],"schema":"wellmanifest.logs/error/v1","severity":"ERROR","title":"MCP tool returned isError=true","verification":["Inspect the correlated interaction and confirm the documented failure class.","Run python -m pytest -q tests/test_gateway.py before publication."],"version":1}
```

## Situation

MCP tool returned isError=true.

## Meaning

Use the private interaction link to distinguish observed facts from possible causes.

## Safe resolution

Read the tool response and its runbook. Transport success does not imply tool success.

## Verification

Run the verification commands in the definition and read back a fresh interaction.

## Do not

Do not publish private payloads or blindly repeat an MCP operation after a lost response.

## Related events

The operational event is error_raised; correlate it with subllm.interaction_started.
