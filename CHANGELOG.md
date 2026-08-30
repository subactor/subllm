# Changelog

## [1.9.0] - 2026-08-30

### Added

- Execute sequential, bounded runtime failover in `complete()` when a routed
  provider stalls, has a transport failure, returns a transient/auth/rate HTTP
  status, reports a missing model, or produces an invalid completion response.
- Keep process-local provider health receipts and temporarily prefer healthy
  route candidates after a failure or an excessively slow successful response.
- Include secret-free attempt metadata on successful `CompletionResponse`
  values and bounded provider/model outcomes in terminal errors.
- Configure attempt timeout, slow-response threshold, cooldown, failure
  threshold and maximum attempts centrally in `subllm.toml` schema v3.

### Security

- Runtime failover never adds a provider/model outside the exact route, never
  starts speculative parallel calls and does not replay mutable Aider edits.

## [1.8.1] - 2026-08-29

### Changed

- Route Validator OpenRouter fallback to `z-ai/glm-5.3-flash` on
  `patch-review` and `direct-pr-review` while keeping Repair on `z-ai/glm-5.3`.

## [1.8.0] - 2026-08-29

### Added

- Mark routes with modality `text` or `vision`. Vision routes accept OpenAI
  `image_url` parts and never select Cursor SDK.
- Catalogue OpenRouter `z-ai/glm-4.5v` and mark `gemini-3.6-flash` as vision.
- Register `autogrammar-nexu/vision`, `autogrammar-nlp2cmd/vision`,
  `autogrammar-vql/vision` and `autogrammar-imgl/vision`.
- Reject image parts on text routes, missing images on vision routes, and
  non-https / non-`data:image` URLs.

## [1.7.0] - 2026-08-28

### Added

- Add OpenRouter catalog bindings for `z-ai/glm-5.3` and
  `z-ai/glm-5.3-flash`.
- Route Z.AI connectivity fallback by role: GLM 5.3 Flash for Repair and GLM
  5.3 for Validator plus the host coding-agent `onedev-agent/code-edit` route.

### Changed

- Document provider ordering separately from role-specific model selection.

## [1.6.0] - 2026-08-28

### Added

- Register the central `skills-agent/process-editor` LLM route and the closed
  `poa://subactor.subllm/process/edit-process/v1` process.
- Validate exact-base, editable-path process DSL proposals through one
  CLI/HTTP `PolicyBus`, producing secret-free events, candidate digests and a
  terminal receipt without publishing or granting authority.

### Security

- Reject edits to process identity, allowed actions, deterministic controls,
  editor authority and publication gates, including attempts to inject those
  fields into an untrusted editable-path list.
- Reject secret-bearing command payloads before any journal event is appended.

## [1.5.0] - 2026-08-26

### Added

- Execute policy-selected Cursor SDK routes through the same public
  `subllm.complete()` entry point as Z.AI and OpenRouter. Cursor execution is
  tool-free and retains the configured project working directory.
- Register `koru-agent/reflection` alongside Koru planning and queue routes.
  All three use the centrally configured Z.AI → Cursor → OpenRouter
  pre-request selection chain.

## [1.4.2] - 2026-08-26

### Added

- Register the policy-owned `semcod-nfo/analyze` route so NFO log analysis
  prefers direct Z.AI `glm-5.3` through the public completion API.

## [1.4.1] - 2026-08-26

### Added

- Register policy-owned `prellm/preprocess` and `prellm/execute` routes that
  prefer direct Z.AI `glm-5.3`.

### Fixed

- Discover the repository policy from isolated worktrees whose directory name
  is not exactly `subllm`.

## [1.4.0] - 2026-08-26

### Added

- Add zero-dependency `complete()` execution for policy-resolved
  OpenAI-compatible routes.
- Return typed, secret-safe completion metadata without replaying a started
  request through another paid provider.

## [1.3.1] - 2026-08-26

### Fixed

- Align packaged built-in defaults with the repository policy so installations
  outside the source checkout prefer direct Z.AI `glm-5.3`.

## [1.3.0] - 2026-08-26

### Changed

- Prefer direct Z.AI `glm-5.3` for every registered application/function
  route, including todo2code and Koru.
- Retain Cursor and OpenRouter only as pre-request fallbacks; a started Z.AI
  request is never replayed automatically through another paid provider.
- Verify the direct Z.AI preference across the complete route catalog.

## [1.2.0] - 2026-08-21

### Added

- Add the direct Z.AI `glm-5.3` catalog entry and pin it to
  `validator-agent/patch-review` and `validator-agent/direct-pr-review`.

### Changed

- Keep every other application on its existing provider defaults and retain
  OpenRouter `z-ai/glm-5.2` as the Validator fallback.

## [0.8.0] - 2026-08-19

### Added

- Adopt `wellmanifest/poa` as a CQRS/ES invoker: closed process refs, query
  and command URIs, event journal and receipts.
- Expose the same bus on CLI (`subllm poa`) and localhost HTTP (`subllm serve`).
- Project the process catalog to `policy/adopted/poa/process-catalog.json`.

### Changed

- Existing inspect CLI commands route through `PolicyBus` without changing
  their public output.

## [0.7.1] - 2026-08-18

### Added

- Add `platform/site-audit` for `wellmanifest/webpage` site-wide UX judgment.
  Consumers observe DOM/tokens locally and ask the model for kind, budgets and
  hints. The route uses the same candidate chain as `platform/interactive`.

## [0.7.0] - 2026-08-16

### Added

- Add strict `koru-agent/planning-assistant` and `koru-agent/queue-executor`
  routes using Cursor `grok-4.6` with `effort=xhigh` and `fast=false`.
- Carry route-level Cursor model parameters through `cursor_sdk_kwargs()`.
- Add the `cursor` installation extra for consumers that execute Cursor SDK
  routes.
- Discover the shared credential file at
  `<workspace>/subactor/subllm/.env` from sibling project checkouts.

### Changed

- Koru routes fail closed when `CURSOR_API_KEY` is unavailable; they never
  fall back to Sol, Z.AI, OpenRouter, or another Cursor preset.

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
