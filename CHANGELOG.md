# Changelog

## [0.6.1] - 2026-08-16

### Added

- Cursor allowlist peer `grok-4.6` (exact SDK slug). Fleet fallback order on
  Cursor: `gpt-5.6-sol` then `grok-4.6`; `resolve()` still defaults to Sol.

### Fixed

- Autouse pytest fixture clears live `CURSOR_API_KEY` / Z.AI / OpenRouter
  process env so workspace discovery tests stay hermetic.

## [0.6.0] - 2026-08-16

### Changed

- Assign LLM strategies by API-key source. `gpt-5.6-sol` is Cursor-only
  (`cursor-sdk`); OpenRouter no longer claims `openai/gpt-5.6-sol`.
- `resolve()` may return `provider=cursor` when `CURSOR_API_KEY` is valid.
  Use `cursor_sdk_kwargs()`; `litellm_kwargs()` rejects Cursor transport.
- Fleet priorities: cursor `0` / Sol, zai `10` / glm-5.2, openrouter `20` /
  glm-5.2.

### Added

- ADOPT projections from `wellmanifest/policy-dsl` (`llm-credential`) and
  `wellmanifest/env-dsl` (`subllm-credential-strategies.env`) under
  `policy/adopted/` plus `docs/credential-strategies.md`.
- Catalog entry `gpt-5.6-sol` for the Cursor provider only.
- Accept `CURSOR_API_KEY` from the shared ignored `.env`.
- Add `SUBLLM_PROVIDER_ORDER` for the pre-request fallback chain.

## [0.5.0] - 2026-08-12

### Added

- Added the `todo2code/semantic` route with direct Z.AI GLM 5.2 preferred
  before the OpenRouter GLM 5.2 fallback.
- Added the public `todo2code` application identity used for provider-visible
  request attribution.

## [0.4.1] - 2026-08-12

### Fixed

- Route direct Z.AI calls through the account's GLM Coding Plan endpoint.
- Reject malformed `ID.ID.secret` credentials before transport so configured
  OpenRouter selection remains available.

## [0.1.0] - 2026-08-11

### Added

- Added the central Subactor provider, model, application and function routing
  policy.
- Added credential-aware route resolution with direct Z.AI preference and
  OpenRouter fallback for GLM 5.2.
- Added safe public serialization, LiteLLM adapter kwargs and a read-only CLI.
