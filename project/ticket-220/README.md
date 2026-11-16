# Ticket 220: Serve configured speech inference and shared runtime profiles through the SubLLM proxy

- **ID**: ticket-220
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-16
- **maxActiveMinutes**: 120

SESSION_EXECUTION_AUTHORIZATION: the user requested configuration of all LLM,
TTS, STT and URI decision parameters in Heyasa/WillmOS, with all inference
through a configured local or remote OQLLM instance backed by SubLLM.
Implementation, tests and protected publication are authorized in this session.

## Goal and scope

Provide the shared runtime profile schema, validation, atomic private storage
and gateway client in the canonical SubLLM SDK. Extend the existing proxy with
bounded speech transcription/synthesis operations and explicit capabilities.
The OQLLM gateway remains the application-facing entry; provider adapters and
speech inference remain behind SubLLM. Support installed local Whisper/Piper
backends and explicitly configured remote speech providers without silently
falling back to text generation or bypassing the selected gateway.

Keep typed D1 decisions and application URI/consent gates intact. Credentials
must remain private and must not carry over to a changed gateway address.
Do not change external publication policy, active deployments or unrelated
provider routes. Cross-repository consumers are Heyasa ticket-685 and the
separately scoped Willmux integration.

Bounded scope refinement: `client_routes.py` must carry validated per-request
sampling parameters into the canonical provider invocation. The existing proxy
otherwise drops these controls. A fresh work-start observation found that exact
path free; this remains the same requested all-role configuration outcome.
Operator token ceilings, request snapshots, audit and cache correctness remain
mandatory.

## Acceptance criteria

- [x] AC-01: A shared versioned profile describes gateway, all four model roles
  and supported parameters, with strict validation and public credential redaction.
- [x] AC-02: Private profile writes are atomic, revision checked and preserve
  request snapshots during concurrent configuration changes.
- [x] AC-03: Proxy speech operations validate audio/parameters, return truthful
  backend results and retain explicit provider failures without text fallback.
- [x] AC-04: Meaningful profile, transport and proxy regressions pass through
  the approved project runtime; governance passes.
- [ ] AC-05: Publication uses fresh exact-head local CI and independent Validator
  approval through the protected controller; no direct merge occurs.

Local evidence: 225 transport, generation-limit, cache and proxy regressions
passed. After formatting and native option propagation, 98 affected tests
passed; the final native-route observation then passed all 30 profile/audio
tests. Ruff passes and the managed test hook reports 0 governance errors or
warnings. Token caps include legacy string-valued operator settings.

The canonical SDK candidate is built only for isolated consumer verification;
it is not a published release. Protected CI, independent review, the release
artifact and enrolled production activation remain separate prerequisites.
Consumers are Heyasa ticket-685 and the current owner of Willmux ticket-621.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 56/100 |
| Complexity | M |
| Estimated effort | 60 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
