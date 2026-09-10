---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "routing-contract",
  "kind": "information",
  "version": 1,
  "title": "Versioned routing contract for consumers",
  "status": "implemented",
  "owner": "subactor/subllm",
  "created": "2026-09-10",
  "updated": "2026-09-10",
  "review_after": "2026-10-10",
  "source_revision": "8020d8db8bb7a99ea14c37de4cce85eaa8d1bb5d",
  "affected_repositories": ["subactor/subllm"],
  "evidence": ["repo://subactor/subllm/tests/test_routing_contract.py", "https://github.com/subactor/subllm/issues/59"]
}
---

# Routing contract

<!-- docs:section purpose -->
## Purpose

Export central policy for an exact application/function pair. Provider/model/application membership remains in policy.py; operator enablement, priority, defaults and application identity remain in subllm.toml.

<!-- docs:section scope -->
## Scope

`subllm contract platform interactive` and `subllm contract validator-agent direct-pr-review` use the same PolicyBus query boundary as localhost HTTP. The registered URI is `subllm://local/policy/query/export-routing-contract`. Export never appends an event or reads credentials. Request-level provider allowlists are applied by consumers after loading the canonical profile and must be reported separately.

<!-- docs:section evidence -->
## Evidence

The contract tests compare exported candidates with the central resolver, check query event count, distinguish CLI and Validator profiles, and reject modified artifacts, wrong pins and unknown profiles. This implementation does not establish consumer adoption or production activation.

<!-- docs:section content -->
## Content

The `subllm.routing-contract/v1` envelope contains version 1, application, function, candidates, execution settings and sha256. Candidate fields match ConfiguredRoute.public_dict. Floating-point execution settings are decimal strings to preserve their values within the integer-only canonical JSON domain.

The digest is SHA-256 over the canonical JSON of every field except sha256, using SubLLM's restricted RFC8785 domain. A consumer must obtain its expected digest independently from its reviewed source/package pin, verify the profile and schema, then verify the artifact digest. Trusting only the embedded hash is insufficient. The Python verification helper enforces that boundary. Source revision and deployed image digest belong in the consumer's deployment pin and receipt; a contract digest is not deployment evidence.

<!-- docs:section limitations -->
## Limitations

Loading is query-only and grants no credential, execution or publication authority. Version 1 does not persist provider health. A deployment may narrow providers, models and execution budgets explicitly; it must not add candidates absent from the loaded profile or silently increase budgets. Changes to canonical policy require a refreshed exported artifact and independent consumer pin review.

<!-- docs:section next_actions -->
## Next actions

Replace consumer-authored candidate tables with generated, pinned exports. Record source revision, contract version/digest, exact profile, runtime overrides and image digest, then compare the live receipt with the reviewed deployment binding.
