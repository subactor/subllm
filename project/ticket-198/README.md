# Ticket 198: Add tag-bound OIDC PyPI release workflow and package verifier

- **ID**: ticket-198
- **Owner**: agent:antigravity
- **Status**: IN_PROGRESS
- **Workflow state**: PUBLICATION
- **Created**: 2026-11-11

## Goal and scope

SESSION_EXECUTION_AUTHORIZATION: user explicitly requested completing the protected release workflow and package qualification gates for `subactor/subllm#20`.

Add a tag-bound GitHub Actions workflow (`.github/workflows/publish.yml`) using PyPI Trusted Publishing (OIDC) together with a deterministic, stdlib-only release verifier (`scripts/verify-release-package.py`) and regression suite (`scripts/tests/test_release_package.py`). Keep `subactor/subllm#20` open until `subactor-procache==0.1.0` is published on PyPI and PyPI Trusted Publisher registration completes.

## Acceptance criteria

- [x] AC-01: `scripts/verify-release-package.py` binds optional `v*` release tags to `pyproject.toml` `[project].version`, validates wheel and sdist metadata (rejecting PEP 440 direct-URL `Requires-Dist` entries and requiring `subactor-procache==0.1.0` in cache/test extras), and verifies in an isolated wheel subprocess that all six Semcod/Autogrammar routes resolve `zai` / `glm-5.3` first with zero network calls.
- [x] AC-02: `--check-pypi-index` fails closed before upload if `subactor-procache==0.1.0` is missing on the target index, if `>= 5` `subactor-subllm` releases were already uploaded on the current UTC calendar day, or if an existing target release digest mismatches; `--verify-pypi-published` confirms exact wheel and sdist SHA-256 digests on the index before GitHub Release creation.
- [x] AC-03: `.github/workflows/publish.yml` uses least-privilege permissions, protected `pypi`/`testpypi` environments with OIDC (`id-token: write`), safe environment-variable binding (no untrusted expression interpolation in shell scripts), and creates a matching GitHub Release only after PyPI SHA-256 readback succeeds; `pyproject.toml` includes `scripts/tests` in `testpaths` so both `./scripts/verify` and OneDev execute the suite.

## Tracking boundary

This directory contains the minimal reviewed intent. Optional participant prose
and raw command logs are not required delivery output.
