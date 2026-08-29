---
participant-id: agent:grok
participant: grok
role: agent
ticket: ticket-022
---
# Participant: grok

## SESSION_EXECUTION_AUTHORIZATION

2026-08-29 user: nexu needs vision, so extend SubLLM with vision application
support and continue the consumer migration.

## Understanding

Cinema/CAPTCHA/VQL send `image_url` parts. Text routes must not silently drop
images onto GLM 5.3 / Cursor. Vision is a route modality, not a YAML model
override.

## Execution plan

1. Add `ModelSpec.vision` and `RoutePolicy.modality`.
2. Catalogue `glm-4.5v`; mark `gemini-3.6-flash` vision.
3. Register `autogrammar-nexu/vision` (and nlp2cmd/vql vision).
4. Fail closed in `complete()` for modality mismatches.
5. Keep nexu YAML custom-model LiteLLM path for later consumer work.

## Actual changes

See the ticket-022 diff on branch `ticket/022-vision-routes`.
