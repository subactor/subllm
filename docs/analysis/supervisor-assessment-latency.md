---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "supervisor-assessment-latency",
  "kind": "analysis",
  "version": 1,
  "title": "Bounded reasoning for periodic supervisor assessment",
  "status": "accepted",
  "owner": "subactor/subllm",
  "created": "2026-09-06",
  "updated": "2026-09-06",
  "review_after": "2026-09-13",
  "source_revision": "c81418a99d75dbc1ee2376d0871c50203b42ac35",
  "affected_repositories": [
    "subactor/subllm"
  ],
  "evidence": [
    "https://docs.z.ai/guides/llm/glm-5.3",
    "https://github.com/subactor/subllm/issues/45",
    "receipt:sha256:9a0ee28c45bd089dad1d0ea6932b1d0d0ed5902580a2fcaa5f99bb3c9013ea97"
  ]
}
---

# Bounded supervisor assessment reasoning

<!-- docs:section question -->
## Question

Can the periodic supervisor/assessment route finish a useful structured assessment within its existing timeout without changing models or authorization?

<!-- docs:section scope -->
## Scope

This document owns the local SubLLM route parameter decision. Supervisor inputs are an integration fixture; the broader autonomy audit remains in subactor/docs/architecture/analysis/supervisor-autonomy.md.

<!-- docs:section method -->
## Method

Read the deployed completion settings and recent outcomes. Send one short request through the same installed SubLLM route. Replay one captured, secret-free assessment context with only direct ZAI reasoning_effort changed to low. Validate returned content using the Supervisor closed schema. Do not execute the returned decision.

<!-- docs:section evidence -->
## Evidence

On 2026-09-06 the short probe succeeded in 2.77 seconds (ZAI GLM-5.3, 166 tokens). The low-effort full-context replay succeeded in 13.58 seconds (10,742 prompt tokens, 919 completion tokens, including 167 reasoning tokens). The returned no_action assessment passed the Supervisor schema. The private raw response has the digest in metadata; it is not publicly retrievable evidence. Prior live attempts repeatedly reached the configured 180-second attempt / 240-second total budget.

<!-- docs:section facts -->
## Facts

The previous assessment candidate supplied no reasoning_effort. ZAI documents max as the GLM-5.3 default, accepts low/high/max, and does not support disabling reasoning. The short successful probe shows the provider was reachable at that instant.

<!-- docs:section hypotheses -->
## Hypotheses

Default maximum reasoning contributes to full-assessment latency. The observed speed difference is consistent with this hypothesis, but the single replay is not a controlled latency or decision-quality benchmark; server load and request differences may contribute.

<!-- docs:section limitations -->
## Limitations

No percentile, fleet reliability or improved decision accuracy claim is supported. A schema-valid answer can still be semantically wrong. Existing decision, authority and receipt gates remain necessary. OpenRouter and Cursor fallback settings are unchanged. Planning, coding, repair and supervisor review retain existing reasoning defaults.

<!-- docs:section recommendations -->
## Recommendations

Set reasoning_effort=low only on the direct ZAI candidate for supervisor/assessment, deriving candidates from the shared default list. Verify a fresh live assessment after deployment and retain its receipt externally. Compare timeout rate, latency and decision correctness over subsequent real cycles. Roll back this route parameter if assessment quality regresses; never compensate by weakening authority or schema checks.
