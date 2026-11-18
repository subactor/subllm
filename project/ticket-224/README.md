# Ticket 224: Support installed Vosk models through the shared speech gateway

- **ID**: ticket-224
- **Owner**: agent:codex
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-18

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION from PLF-27203. Support an installed Vosk language model through SubLLM's existing transcription route so the Heyasa and Willmux shared profiles can reuse it. Decode only bounded user-supplied clips, without microphone access, model downloads or action dispatch. Keep the existing Whisper, Piper and remote contracts.

Configure the service with the optional Python modules `vosk` and `av`. Set `SUBLLM_SPEECH_MODEL_ROOTS` to the directory containing the installed Vosk model. Select the model directory reported by `GET /v1/ai/capabilities`. In the shared AI profile, set `roles.stt.parameters` to `{"engine":"vosk"}` and `roles.stt.model` to that directory. Model selection determines the recognition language. Heyasa and Willmux use `POST /v1/speech/transcribe` for the supplied audio clip.

## Acceptance criteria

- [x] AC-01: Discover installed models and select a Vosk model explicitly.
- [x] AC-02: Bound and normalize audio to mono PCM, retain all finalized utterances and reuse the loaded model across requests.
- [x] AC-03: Validate client paths with synthetic Polish speech and run regression tests.

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
| Estimated effort | 54 min |
| Planning budget | 30 min |
| Split recommended | yes |

Diagnostics: RADAR-ACCEPTANCE-MISSING, RADAR-BUDGET-EXCEEDED.
<!-- ticket-radar:end -->

## Device qualification

On 192.168.188.70 the Heyasa client and the Willmux client each used their shared profile, a temporary REST key scoped to voice, an isolated OQLLM relay and this SubLLM adapter. Piper produced Polish WAV audio. The installed-language-model fixture from STTS, `vosk-model-small-pl-0.22`, returned “to jest próba rozpoznawania polskiej mowy” for both clients. OQLLM returned 401 without credentials. The test used temporary processes and model files; the running system services still returned 404 on the capabilities route. Production packaging needs the runtime, model and OQLLM speech relay.

The focused suite passed all 58 tests with PyAV installed. Additional real Opus clips in Ogg and WebM containers each decoded from 0.25 seconds of stereo audio to 4000 mono samples at 16 kHz.
