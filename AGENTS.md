# subllm agent instructions

- Keep provider, model and application/function routing policy in
  `src/subllm/policy.py`; consumers must not grow private copies.
- Never add API keys, key IDs, secret fragments, tokens or `.env` files.
- A new provider needs credential-shape tests and a fixed HTTPS API base.
- A new route needs an exact application/function pair and deterministic
  priority ordering.
- Never silently fall back to a model that the route does not list.
- Run `./scripts/verify` before completing a change.

