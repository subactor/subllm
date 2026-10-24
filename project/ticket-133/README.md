# Ticket 133: Separate proxy test client waiting from application deadlines

- **ID**: ticket-133
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: user requests autonomous completion, testing and protected merge of the SubLLM backlog. This resolves issue137 observed while testing issue134. Scope is disjoint from active ticket132; no production timeout changes. Bounded session60 minutes from2026-10-24T21:41Z.

- [x] AC-01: The internal HTTP test client has a finite configurable socket wait distinct from payload/application timeout.
- [x] AC-02: Controlled loopback delayed response demonstrates short client timeout and successful longer wait; the backend receives the same caller timeout.
- [x] AC-03: Existing model/class/structured-output and timeout regressions, Ruff and governance pass without a paid provider.
- [ ] AC-04: Exact-head OneDev and independent Validator approve and protected controller merges; no closure commit.

Validation:24 proxy tests pass, including controlled delayed loopback response and caller-timeout preservation. Ruff and managed governance pass. No provider inference or database reset. The change to internal test socket waiting leaves production timeouts untouched. Independent publication remains AC-04.
