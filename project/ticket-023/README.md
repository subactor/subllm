# Ticket 023 — resilient runtime provider failover

## Intent

Make `subllm.complete()` finish promptly when a configured provider stalls or
returns a transient availability failure. Candidate membership remains owned by
the exact application/function route; runtime health may only reorder or advance
through those candidates.

## Bounded delivery

- Add operator-owned attempt, total-attempt, cooldown and slow-response limits.
- Advance on bounded timeouts, transport failures, provider auth/rate failures,
  retryable HTTP status codes and invalid provider responses.
- Keep process-local, secret-free provider health receipts so following calls
  prefer a healthy candidate during cooldown.
- Do not issue parallel speculative requests and do not replay mutable Aider
  code-edit executions.
- Cover failover, cooldown, recovery, route boundaries and non-retryable errors
  with deterministic tests.

## Verification

- `./scripts/verify`: 187 tests passed; wheel and source distribution built.
- Live `todo2code/semantic` canary: direct Z.AI returned HTTP 429 in 836 ms,
  unavailable Cursor was skipped, and OpenRouter GLM 5.2 succeeded in 1023 ms.
  The final response contained the expected 11-byte JSON object and exposed a
  three-attempt, secret-free receipt.
