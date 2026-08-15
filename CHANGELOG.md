# Changelog

## [Unreleased]

### Added

- Accept `CURSOR_API_KEY` from the shared ignored `.env` so Cursor SDK
  consumers can use the same workspace credential file. The name matches the
  Cursor SDK (`@cursor/sdk` / `cursor-sdk`). An empty value remains missing.
- Add `SUBLLM_PROVIDER_ORDER` for the pre-request fallback chain. Known ids
  are `cursor`, `zai` and `openrouter`. The default is `cursor,zai,openrouter`
  when `CURSOR_API_KEY` is set, otherwise `zai,openrouter`. Unknown names
  fail closed. `resolve()` still returns only LiteLLM routes.

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
