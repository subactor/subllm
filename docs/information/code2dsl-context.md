---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "code2dsl-context",
  "kind": "information",
  "version": 1,
  "title": "LLM-selected code2dsl editing context",
  "status": "implemented",
  "owner": "subactor/subllm",
  "created": "2026-09-09",
  "updated": "2026-09-09",
  "review_after": "2026-10-09",
  "source_revision": "bcf2a3d7a64512c63c59bc73ac27b1d9e5db47a1",
  "affected_repositories": [
    "subactor/subllm"
  ],
  "evidence": [
    "repo://subactor/subllm/tests/test_code_context.py",
    "repo://subactor/subllm/tests/test_client.py",
    "repo://autogrammar/todo2code/89e72ce991e3f2518b323d2d5e45ff7368b46acf/src/extractors/ast.ts",
    "receipt:sha256:3c5f255bff00e070d9c3f54d88323abd8cde28747c15206af0a026f25e08e8de"
  ]
}
---

# LLM-selected code2dsl editing context

<!-- docs:section purpose -->
## Purpose

Replace lexical prompt-to-path matching and whole-file Aider attachments with a semantic query over canonical `code2dsl` evidence. Ordinary words such as `tests`, `docs` and Polish `testów` no longer expand directories. This implementation is based on the source revision in metadata; the changes and validation belong to ticket-053.

<!-- docs:section scope -->
## Scope

SubLLM owns the `onedev-agent/code-context` selection route and the `onedev-agent/code-edit` editing route. Both use the central coding model candidates and the existing completion/failover policy. An explicitly selected provider remains an allowlist. The canonical extractor remains `autogrammar/todo2code`'s public `code2dsl` API, emitting validated `t2c.intent/v1` records; this adapter does not copy its parsers or introduce a replacement code DSL.

This delivery supports Python and JavaScript/TypeScript (including JSX/TSX). It changes the existing `subllm-code-edit` implementation and keeps its result envelope and `--aider-bin` compatibility argument. Aider is no longer launched. The outer coding worker continues to own ticket scope validation, repository checks, commits and protected publication.

<!-- docs:section evidence -->
## Evidence

A live synthetic canary on 2026-09-09 used Z.AI GLM-5.3 for both selection and editing. The fixture had 51 tracked files and an `auth.py` of 300,033 bytes. The selection payload contained 1,638 UTF-8 bytes; the editing payload contained 1,763 bytes, including the task and DSL records. These measurements exclude the short system instructions. The model changed `allow(user)` to reject `None`; local assertions checked both `None` and an empty dictionary and verified all 15,000 unrelated padding lines remained unchanged. Execution took 21.19 seconds. This is a synthetic canary, not a production ticket execution receipt.

The private canary receipt is bound by its SHA-256 in metadata. It contains model names, request sizes and digests, selected IDs, source/build pins and before/after source digests; it does not contain credentials or raw LLM transcripts. `./scripts/verify` passed: 253 tests, lint, bytecode compilation, wheel and sdist builds. The packaged wheel contains the Node bridge. Regression tests cover semantic selection across large inventories, paged reduction, invalid model IDs, path boundaries, stale source, digest mismatches, overlapping edits, truncated excerpts, Python syntax, real Python/JS extraction and preserved operator ignore rules.

<!-- docs:section content -->
## Content

1. Inventory tracked eligible source files and copy them into a private temporary snapshot. Exclude hidden paths, dependency caches, symlinks and binary data. Preserve `.gitignore`, `.dockerignore`, `.intentignore` and the operator's Aider ignore policy. Neither source import nor extraction executes repository code.
2. Verify the explicitly configured todo2code source SHA and independent runtime build digest. The build digest covers executable JavaScript, Python helpers, TypeScript parser files and the runtime package metadata. Call `code2dsl` through the packaged Node bridge without credentials, `.env` loading, caches or an LLM in extraction.
3. Send paged DSL projections to the registered selection LLM. These contain source IDs/ranges, symbols, semantic statements and metadata; selection does not receive `rawExcerpt` or source file buffers. Validate every returned ID against its exact page. If necessary, ask the LLM to reduce the candidates in bounded additional passes. There is no regex/path fallback.
4. For selected records, use the canonical DSL's bounded node excerpts for editing. A record is editable only when its excerpt covers the complete source range, is at most 2,000 characters, and is not a module summary. Incomplete records can provide context but cannot replace unseen code. This is intentionally different from attaching every selected source file. Small nodes may naturally contain all code in a very small file.
5. The editing LLM returns record IDs, original file hashes and replacements for those exact line ranges. Validate every edit, reject unknown IDs and overlapping ranges, check Python syntax, and reobserve source bytes before writing. Preserve all bytes outside selected ranges and preserve file modes. Replace individual files atomically; the outer worktree/lease remains responsible for excluding concurrent writers and for recovery after interruption.
6. Return a secret-free `subllm.dsl-edit-receipt/v1` inside the existing result's `response`: extractor pins, query provider/model and byte counts, request digests, selected record IDs and edit digests. A receipt is evidence of local edits, not merge or deployment authority.

Configure the trusted worker environment with all three values:

```text
SUBLLM_CODE2DSL_RUNTIME=<absolute path to the verified todo2code runtime>
SUBLLM_CODE2DSL_SHA=<40-character source commit>
SUBLLM_CODE2DSL_BUILD_SHA256=<independently approved build digest>
```

The observed canary runtime source was `89e72ce991e3f2518b323d2d5e45ff7368b46acf`, with build digest `0dbae665d10b325fc78d7a9133d8e2efb7f818b68b9c3b9f802a0e2ed1937842`. The digest algorithm is `subllm.code_context.runtime_digest`. Computing a digest is an observation; operators must bind it to independently reviewed build provenance rather than trusting a candidate runtime to approve itself. No sibling-directory discovery or automatic unpinned runtime fallback exists.

<!-- docs:section limitations -->
## Limitations

The current code2dsl facade provides structural facts and bounded excerpts, not a lossless representation of arbitrary source. Large indivisible nodes, unsupported languages, documentation/configuration edits and creation of new files require further canonical extractor/edit-contract coverage; they are not silently handled by sending whole files or guessing original content. Source extraction is bounded separately (20,000 source files, 8 MiB per file, 64 MiB total). Query pages are bounded to 48,000 bytes, with at most 128 pages and 32 final selected records. These are operational bounds, not claims about any model's context window.

LLM selection is advisory and can omit a relevant dependency. If it produces no supported edit, execution fails explicitly. Hash/range checks prevent stale or out-of-range application; they do not prove semantic correctness. Full repository tests and independent publication checks remain necessary. Python syntax is checked locally; other supported languages still rely on the outer repository's tests. Multi-file application is not crash-atomic. Production activation and retrying the four PLF tickets have not been performed by this change.

<!-- docs:section next_actions -->
## Next actions

Publish through the independent local Validator under publication authorization, bind the reviewed SubLLM package and the three code2dsl runtime values in the coding worker deployment, then observe a controlled production ticket execution before broader queue retries. Do not activate this change by editing an unreviewed protected runtime directory. Extend language/document/new-file coverage through the respective canonical extractors and a versioned edit contract.
