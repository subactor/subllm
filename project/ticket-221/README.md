# Ticket 221: Bound browser speech audio before inference

- **ID**: ticket-221
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-17
- **maxActiveMinutes**: 120

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: the user requested continued implementation,
tests and protected merges for all speech through the configured OQLLM/SubLLM
gateway. Browser MediaRecorder input currently omits media_type and is treated
as WAV; compressed audio also lacks the existing WAV decoded-duration limit.

Identify supported WAV, WebM and Ogg containers from bounded input when the
type is absent. Check explicit types against the container. Validate compressed
audio incrementally through the existing faster-whisper PyAV dependency and
stop after 120 seconds of decoded samples, before model or remote inference.
Reject invalid streams or unavailable decoding without a fallback provider.
Preserve raw clips and existing role/model/parameter choices. Do not change
resolver.py, package manifests, model downloads or production services.

The allocator used primary HEAD 69e33df; before implementation, integrate the
already fetched and independently merged SDK/audio base
02a13e7b3a24369da1edb17e3253973d361ade80 in this canonical linked checkout.
Preserve and regenerate this ticket's allocator index. The primary checkout's
unrelated resolver.py changes remain untouched.

## Acceptance criteria

- [x] AC-01: Missing or parameterized browser media types are identified and
  mismatched/invalid containers fail before inference.
- [x] AC-02: Decoded compressed duration, sample rate and channel bounds are
  enforced independently of untrusted container metadata and decoder errors.
- [ ] AC-03: Focused and regression tests plus real codec qualification and
  managed governance pass; independent exact-head approval controls merge.

Validation: 54 audio/profile tests passed, including early termination before
model/provider calls and exact 120-second accounting. Real libopus WebM and
Ogg clips at 0.1 and 120 seconds were accepted; 120.1-second clips were rejected.
PyAV 19.0.2 qualification invoked no microphone, model or external provider.
Ruff passed. Native CI and independent exact-head review remain pending.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.

<!-- ticket-radar:start -->
## Ticket Radar

Initial planned-scope estimate; advisory only, not execution or merge approval.

| Measure | Initial assessment |
| --- | --- |
| Impact score | 52/100 |
| Complexity | M |
| Estimated effort | 51 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->
