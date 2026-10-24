# Ticket 135: Typed route catalog and proposal editor

- **ID**: ticket-135
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: user requests autonomous continuation, implementation, tests and protected merging of the SubLLM backlog. This implements issue24. Gemini3.8 Flash is the requested advisory model. Session bounded120 minutes from2026-10-24T23:26Z. Legacy defaults and runtime TOML remain compatible for one release. The proposed catalog never grants approval or changes a deployment.

- [x] AC-01: Versioned JSON/TOML defines approved providers/defaults, aliases, applications/functions and ordered candidates; strict bounds and semantic references compile to immutable existing runtime objects.
- [x] AC-02: Explicit process-start activation requires exact file pin and safe regular path. Code-owned adapters, credentials, forbidden models and native execution limits remain in code; legacy callers/configuration stay compatible.
- [x] AC-03: Schema-aware editor exports/checks a catalog and creates validated bounded patch proposals with base digest and exclusive output; route evidence contains a semantic effective-policy digest without credentials.
- [ ] AC-04: Parity, malformed input, activation, proposal, unknown-route and digest regressions plus full stack/governance and independent exact-head merge pass.

Validation: 33 catalog regressions and 195 catalog/policy/resolver/configuration checks pass; Ruff, compile, wheel/sdist build, adopted Logs and governance pass. The initial full run passed801 tests but the shared PostgreSQL usage query hit its existing statement timeout. An isolated, ticket-owned local PostgreSQL then passed all4 backend tests. The final full run disables automatic discovery of the shared development database; its backend skip is covered by that isolated integration run. External check reports are retained under session-receipts/subllm-catalog-20261024T2326. Independent exact-head CI/review/merge remain pending. No deployment or active operator file changes.
