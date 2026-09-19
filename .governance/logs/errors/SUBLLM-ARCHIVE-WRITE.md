# SUBLLM-ARCHIVE-WRITE: Private archive write failed

## Error DSL

```log-error-dsl
{"category":"STORAGE","causes":["The configured database could not complete the requested storage operation."],"code":"SUBLLM-ARCHIVE-WRITE","doNot":["Do not expose credentials or private messages in public logs.","Do not automatically retry MCP tools whose side effects are unknown."],"meaning":"Private archive write failed","owner":"service:subllm","relatedEventTypes":["error_raised"],"remediation":["Check database availability, permissions and free space; do not repeat a completed paid or tool call."],"schema":"wellmanifest.logs/error/v1","severity":"ERROR","title":"Private archive write failed","verification":["Inspect the correlated interaction and confirm the documented failure class.","Run python -m pytest -q tests/test_gateway.py before publication."],"version":1}
```

## Situation

Private archive write failed

## Meaning

Storage failed; upstream execution may already have completed.

## Safe resolution

Check database availability, permissions and free space; do not repeat a completed paid or tool call.

## Verification

Verify archive connectivity and reread the correlated interaction.

## Do not

Do not retry paid calls or tools to repair their archive.

## Related events

Use error_raised for the storage failure. If persistence itself is unavailable, the fixed code is sent to stderr.
