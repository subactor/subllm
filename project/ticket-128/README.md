# Ticket 128: Bounded DeepSeek V4.1 cost and latency routing

- **ID**: ticket-128
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Workstream**: application

SESSION_EXECUTION_AUTHORIZATION: user explicitly requests backlog execution, new DeepSeek 4.1 work and cost/latency-aware LLM management. Gemini 3.8 Flash remains the preferred advisory model. Maximum active source session: 120 minutes from allocation, checkpoint every material boundary.

- [x] AC-01: Register exact DeepSeek V4.1 alias/snapshot and a dedicated opt-in route without changing existing role preferences.
- [x] AC-02: Forward validated OpenRouter price caps, provider allowlist, latency/throughput preferences and bounded output cap through ordinary and catalog completions; reject malformed policy without weakening existing constraints.
- [x] AC-03: Quote endpoint costs using input/output/cache token mix and already-discounted per-token prices; retain freshness, model, capability, context and budget guards. Missing latency remains unknown; hard latency constraints exclude it.
- [ ] AC-04: Focused tests, complete stack verification and governance pass before exact-head independent publication. No global policy or credential mutation.

Research observations are external raw receipts pending the separately scoped integration research deliverable. OpenRouter account availability and live inference latency are distinct from public endpoint catalog availability.

Validation: 181 focused route/proxy/worker and quote tests pass, including malformed metrics and numeric overflow. Governance passes. Initial full verification found the existing sibling-policy discovery defect (fixed independently by native ticket130 / PR131) and a shared PostgreSQL statement timeout. Full verification must be repeated against the integrated repair using the owned disposable PostgreSQL fixture; neither initial failure is hidden or waived. GitHub feature issue130 is distinct from native bug ticket130.

- [x] AC-05: Normalize explicit policy selection consistently for discovery and source-role metadata; cover whitespace-only values and padded explicit paths. This bounded dependency repair follows the independent PR131 advisory finding. The same-session recovery predecessor is preserved in a verified private Git bundle and its existing read-only recovery ref; no branch or unknown data is discarded.

Accepted base refreshed to the independently merged PR131 result before the expanded provenance repair. Two new regression cases failed before the normalization fix and pass afterward. The final complete stack verification is recorded externally and in the PR; earlier failed runs remain retained.

The final implementation is rebuilt atomically from the verified base. This avoids importing an older predecessor commit that lacks this ticket intent; the failed governance run is retained and its gate is not waived.
