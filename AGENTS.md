# subllm agent instructions

- HOME is `subactor`. Shape is `both` (policy library + runtime invoker).
  ADOPT `wellmanifest/poa`, `wellmanifest/env-dsl`, `wellmanifest/modularity`,
  `wellmanifest/new-project` and `wellmanifest/policy-dsl`. Do not HOME those
  packs. Tickets live in `project/`.
- Keep provider/model/application catalogs and route membership in
  `src/subllm/policy.py`. Keep operator-controlled provider enablement,
  priority, default models and application display identity in the root
  `subllm.toml`; consumers must not grow private copies.
- CLI, shell and localhost HTTP must use `subllm.poa.PolicyBus`. Queries
  never append events. Commands append secret-free `poa.event/v1` records.
  Unknown process URIs fail closed. Do not add a generic shell adapter.
- ADOPT `wellmanifest/policy-dsl` profile `llm-credential` and
  `wellmanifest/env-dsl` `subllm-credential-strategies.env`; refresh
  `policy/adopted/` when those catalogs change. Never pin Cursor Sol on
  OpenRouter wire ids.
- Never commit API keys, key IDs, secret fragments, tokens or `.env` files. The ignored local
  `subllm/.env` is the workspace credential source and must stay mode `0600`. Extra SDK names
  such as `CURSOR_API_KEY` belong in that file, not in tracked docs.
- A new provider needs credential-shape tests and a fixed HTTPS API base.
- A new route needs an exact application/function pair and deterministic
  priority ordering. `SUBLLM_PROVIDER_ORDER` is a comma-separated allowlist
  (`cursor,zai,openrouter`); unknown names fail closed.
- Never silently fall back to a model that the route does not list.
- Run `./scripts/verify` before completing a change.

<!-- wellmanifest:docs-placement:start -->
## Documentation placement

Before research or writing, identify the owning repository, document kind and canonical path using [wellmanifest/docs 0.1.0](https://github.com/wellmanifest/docs/blob/fdb0fcaa7c606dc2503cabb71eff64d5f86ee659/docs/standard/POLICY.md). Resolve existing documents through the artifact registry when available; update the canonical document instead of creating duplicates.

- Durable information: `docs/information/<id>.md`.
- Analysis and final reports: `docs/analysis/<id>.md`.
- Refactoring plans: `docs/refactoring/<id>.md`.
- Architecture decisions: `docs/decisions/<id>.md`.
- Index every delivered document in `docs/README.md`.
- Cross-repository results have one owner, `subactor/docs`, under `architecture/{information,analysis,refactoring,decisions}/`, indexed in its root `README.md`. Other repositories link to that source.

Use the standard's JSON metadata and section templates. Keep stable IDs, increment the declared version when findings change, update dates, bind exact source revisions and evidence, and separate facts, hypotheses and recommendations. Preserve historical append-only versioning.

A final report or plan must not exist only in `$HOME/.local/state`, `/tmp`, agent session storage, chat or `project/ticket-*`. Tickets contain bounded intent and a link to the canonical result. Raw logs, transcripts, secrets, working databases, backups and Git bundles remain in private ignored recovery storage; publish only safe receipt references and digests when needed.

Before completion, verify placement, metadata, index links and Git tracking. The final response links to the repository document and states whether it is local, committed, in a PR or merged. Documentation status and session prose never grant execution or merge approval.

The adoption pin is `.governance/docs.json`. Run the checker from the immutable standard revision to validate changed documents. The existing protected delivery checks do not yet invoke this documentation checker; this pin and these instructions do not claim CI enforcement. Report actual validation and publication results.
<!-- wellmanifest:docs-placement:end -->

<!-- wellmanifest:local-ci-publication:start -->
## Local CI and independent publication

Adopt the publication policy from [Wellmanifest/new-project 0.20.10](https://github.com/wellmanifest/new-project/blob/d5f77d83b3752477cfb95a535d0e1ce77f148576/docs/information/local-ci-publication.md).
Immutable source revision: `d5f77d83b3752477cfb95a535d0e1ce77f148576`.
Document SHA-256: `44803480f1d51f64eec81a62335b6725747f01b5f2de78105ebfc4017a7922c6`.
This is publication-policy adoption; it does not establish full governance,
adoption of every Wellmanifest pack, deployed CI or successful verification.

For `semcod/*` and `subactor/*`, prefer the protected local OneDev executor
and independent local Validator App. Preserve the repository's own tests,
required platform matrix, protected checks and actor boundaries. Read the
actual protected Validator profile and OneDev configuration; missing profiles
are coverage gaps. GitHub may host code and PRs without hosting test execution.
A GitHub Actions billing/capacity failure does not prove local CI is unavailable.

Before publication, observe existing local reconciliation and reuse its receipt.
Require verification of the exact PR head with the current base and merge result.
Invoke the trusted local Validator adapter or its existing timer under the
user's publication authorization; never self-approve or merge directly.
Use hosted `dispatch-direct-pr.sh` only when the protected deployment explicitly
selects that transport. This rule supersedes older unconditional hosted-dispatch
examples, while retaining all additional repository requirements.

Retire a hosted check only after equivalent local tests and the required OS
matrix have a successful deployed canary and an independently reviewed policy
migration. Never empty required checks or create synthetic success statuses.
Report declared, configured, deployed, verified and published evidence separately.
The complete fleet audit belongs in `subactor/docs/architecture/analysis/local-ci-adoption.md`.
<!-- wellmanifest:local-ci-publication:end -->
