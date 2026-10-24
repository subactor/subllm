# Ticket 132: Bounded streaming endpoint calibration

- **ID**: ticket-132
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: user requests continuing the SubLLM backlog and intelligent cheap/fast DeepSeek execution. This implements GitHub issue134. Source session is bounded to120 minutes from2026-10-24T20:52:55Z. Existing publication authorization permits only the protected OneDev/Validator process. Gemini3.8 Flash remains the requested advisory model.

- [x] AC-01: Dry-run needs no credentials or provider call; explicit live probes bind fresh exact-model endpoint metadata, fixed workload, provider constraints and finite token/sample/time/advertised-cost limits.
- [x] AC-02: A policy-approved isolated worker parses bounded SSE, comments and usage frames, separates visible TTFT/reasoning/total time, cancels under a parent deadline and never returns generated text, prompts, credentials or raw errors.
- [x] AC-03: Failures and missing accounting stop further calls, reservations remain charged conservatively, shared health/cooldowns and usage telemetry are retained. Fresh profile-bound local observations can rank quotes; insufficient samples remain unknown.
- [ ] AC-04: Relevant regressions, full stack, governance, independent exact-head verification and protected merge succeed. Actual live availability is recorded separately from code completion.

Validation:29 focused calibration regressions and48 combined calibration/native-transport tests pass; Ruff passes. Existing mocked native-transport tests now isolate archive/telemetry I/O; their previously observed PostgreSQL-dependent five-second failures are covered by the passing focused run. Full stack and protected review remain pending. Explicit USD0.001 live budget, one Relace snapshot1017 request: visible TTFT1.519s,total1.519s,34 input/12 output tokens,no cached input,reported USD0.00000838,reservation USD0.000135680. DeepInfra Flex status-5 was rejected without provider dispatch. These are fixed-smoke measurements, not production percentiles. External receipts: subllm-calibration-20261024T2053.
