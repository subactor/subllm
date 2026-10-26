# Ticket 148: Honor explicit provider order and voice Flash routing

- **ID**: ticket-148
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: EDIT

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: operator requests AGY first, subscription Codex/Claude when quota allows, local only after cloud failure, and OpenRouter GLM-5.3-flash instead of5.2. Continuation of STARTER-031 and maskservice PLF-17350. Native147 merged and released;145 disjoint source ownership preserved.

Correct explicit provider order so candidate offsets cannot move a provider behind later providers. Preserve default priorities when no explicit order exists. Remove obsolete OpenRouter GLM5.2 from voice/program-generation. Keep subscription CLI opt-in in operator runtime policy; packaged defaults remain unchanged and existing health/quota checks remain authoritative. Do not reset live health or repeat known exhausted Claude calls. Runtime activation requires independently verified merged immutable artifact.

## Acceptance criteria

- [x] Explicit AGY,Codex,Claude,cloud,local ordering survives large candidate offsets and keeps local last.
- [x] No-order policy and same-provider model ordering remain intact.
- [x] OpenRouter voice/program-generation selects only GLM-5.3-flash.
- [x] Quota-exhausted providers remain excluded by existing health gate.
- [ ] Focused tests, governance, protected delivery and runtime verification recorded separately.

## Validation

183 focused tests passed. Full scripts/verify passed:921tests,1optionalPostgreSQLskip, lint/compile/docs/logs/build succeeded. Global runtime activation and protected publication remain pending.
