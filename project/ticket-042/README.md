# Ticket 042: Payment-required provider failover

- **Status**: IN_PROGRESS
- **Workflow state**: EDIT
- **Workstream**: runtime

SESSION_EXECUTION_AUTHORIZATION: User requested autonomy repairs, tests and protected merge. Reuse existing issue #42 provider-capacity/failover scope.

Observed PLF-13900 stopped on OpenRouter HTTP 402 without trying the remaining explicit route. Classify payment-required as provider-level availability, preserving the HTTP outcome, bounded attempts and same-provider skipping.

- AC-01: HTTP 402 produces a secret-free retryable worker receipt; invalid requests remain terminal.
- AC-02: Real worker classification reaches the next explicitly allowed provider without retrying another model of the rejected provider.
- AC-03: ./scripts/verify and independent exact-head publication pass. The broader issue42 real-executor acceptance remains open.

Canonical receipt: https://github.com/subactor/docs/blob/main/architecture/analysis/autonomy-execution-receipt.md
