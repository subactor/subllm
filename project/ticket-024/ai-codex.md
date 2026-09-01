# Codex evidence

- In 38 Supervisor assessments after 15:00 UTC, 34 used deterministic fallback
  and only 4 completed through an LLM provider.
- `subllm.health` stores cooldowns only in module memory, while Supervisor starts
  one new `subllm-complete` process for every assessment.
- The live failure chain repeatedly retried Z.AI, unavailable Cursor and
  OpenRouter despite the immediately preceding identical provider failures.
- A subprocess regression test now writes a Z.AI cooldown and a fresh process
  observes OpenRouter first; policy order returns after expiry.
- Six concurrent subprocesses preserve all six failure increments. Persisted
  rows contain only counters, expiry, latency and a closed reason label.
