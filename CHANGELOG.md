# Changelog

## [Unreleased]

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
