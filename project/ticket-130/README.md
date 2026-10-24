# Ticket 130: Project-bounded policy discovery

- **ID**: ticket-130
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: user requests execution of overdue SubLLM work and necessary repairs. Implements GitHub issue #128. Source scope is disjoint from DeepSeek ticket-128. Maximum active session 120 minutes from allocation.

- [x] AC-01: Project-local scratch cannot discover sibling repository policies; implicit discovery stops at the registered checkout. Explicit shared roots must be ancestors and cannot escape via symlinks.
- [x] AC-02: SDK defaults-only fixtures require no operator policy; explicit SUBLLM_POLICY_FILE retains shared operator use, but malformed/missing policy still fails closed.
- [x] AC-03: Policy metadata binds source role and content digest; test nested project, linked checkout, operator file, absent policy and symlink cases.
- [ ] AC-04: Focused/full tests and governance pass before independent protected publication. No frozen runtime or adopted hash edits.

Validation: full stack checks passed (693 tests, Ruff, compileall, Docs/Report, logs, sdist/wheel); after preserving explicit relative operator bindings, 133 policy/contract tests passed. The owned loopback PostgreSQL fixture isolated verification from a shared database timeout. Governance passes. Publication remains subject to exact-head OneDev and independent Validator approval.
