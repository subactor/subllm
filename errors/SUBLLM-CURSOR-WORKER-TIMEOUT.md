# SUBLLM-CURSOR-WORKER-TIMEOUT: Cursor worker exceeded its bounded timeout

## Error DSL

```log-error-dsl
{"category":"RUNTIME","causes":["The isolated Cursor SDK worker did not finish within the attempt timeout"],"code":"SUBLLM-CURSOR-WORKER-TIMEOUT","doNot":["Do not make the worker timeout unbounded","Do not terminate only the direct worker while leaving SDK descendants owned by the daemon"],"meaning":"The governed Cursor attempt exceeded its operator-owned time bound, so SubLLM terminated its process tree, reaped adopted descendants and made the failure eligible for declared failover.","owner":"service:subllm-runtime","relatedEventTypes":["error_raised","remediation_completed"],"remediation":["Inspect the secret-free Cursor provider health and attempt receipt","Restore the SDK or provider, or allow declared bounded failover after descendant reaping completes"],"schema":"wellmanifest.logs/error/v1","severity":"WARNING","title":"Cursor worker exceeded its bounded timeout","verification":["Run the real-descendant timeout regression in the long-lived OneDev executor and confirm the child PID is reaped"],"version":1}
```

## Situation

The isolated Cursor SDK worker did not complete within the timeout owned by the
current SubLLM attempt.

## Meaning

SubLLM stopped the worker process group. On Linux the worker is a child
subreaper, so SDK descendants are adopted and collected before the worker
exits; the long-lived host daemon does not inherit zombie processes. The
attempt may then continue only through the declared failover policy.

## Safe resolution

Inspect the secret-free attempt and provider-health receipts. Restore the
Cursor SDK or provider, or allow bounded failover to another declared route
after process-tree cleanup finishes.

## Verification

Run `tests/test_client.py::test_cursor_worker_timeout_reaps_real_descendant`
inside the long-lived OneDev executor and confirm the recorded descendant PID
no longer exists after the timeout.

## Do not

Do not remove the timeout, retry without policy bounds, expose credentials, or
kill only the direct worker while leaving its descendants owned by PID 1.

## Related events

Use `error_raised` for the timed-out attempt and `remediation_completed` after
the process tree is reaped and a declared fallback or later retry succeeds.
