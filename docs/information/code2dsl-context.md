---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "code2dsl-context",
  "kind": "information",
  "version": 8,
  "title": "LLM-selected code2dsl editing context",
  "status": "implemented",
  "owner": "subactor/subllm",
  "created": "2026-09-09",
  "updated": "2026-09-10",
  "review_after": "2026-10-09",
  "source_revision": "13c16ce1e42c586fc6ab53fb2e1742bafda9eeea",
  "affected_repositories": [
    "subactor/subllm"
  ],
  "evidence": [
    "repo://subactor/subllm/tests/test_code_context.py",
    "repo://subactor/subllm/tests/test_client.py",
    "repo://subactor/subllm/tests/test_edit_contract.py",
    "repo://autogrammar/todo2code/89e72ce991e3f2518b323d2d5e45ff7368b46acf/src/extractors/ast.ts",
    "receipt:sha256:3c5f255bff00e070d9c3f54d88323abd8cde28747c15206af0a026f25e08e8de",
    "receipt:sha256:3bd94f546a7aaac70d522e00c0e1fa1ec694bb86d6be2bd4ab88460b87b45994",
    "repo://subactor/subllm/project/ticket-057/intent.json",
    "https://github.com/autogrammar/todo2code/commit/1e986f8953ba21973c6b68c914db8db149b8949a"
  ]
}
---

# LLM-selected code2dsl editing context

### Validated projection restores the 64 MiB bound

Ticket-063 validates complete canonical records before transporting the existing
semantic selection fields. Full-record SHA-256 digests retain conflict detection
even for omitted metadata. Bounded canonical editing excerpts remain available:
exact local line excerpts travel as SHA-256 references and are restored only after
range, length and digest checks; partial excerpts retain their exact text. Module
summaries and excerpts already excluded by the editor are not transported.

The expanded transport limit returns to 64 MiB, with 16 MiB compressed transport
and all source, query and attempt budgets unchanged. The frozen Core base
`e0dbd0829f6e021d97385af1fdb7ec9f6914b546` preserves 67,271 unique records from
1,461 source files in 7,279,456 compressed / 66,484,514 expanded bytes. The frozen
PLF-13849 replay preserves 32,271 records from 785 source files in 3,613,232 /
30,253,356 bytes. These replays use extractor
`cdf29f2c19a0edbab65f76269240502de04c568d`, build
`6df0792e32e57ae58ab87ba81fe381576fc534e3d953daf6773377eb1f68d5ae`.
Receipt: `receipt:sha256:3c279fea325a93a03119e0d6e8b11fd1a19e8233f62f20075f0636490bea09e6`.

Core has only about 0.6 MiB of remaining expanded transport capacity. This is a
measured bounded repair, not support for arbitrarily large repositories. The
unprojected 91,940,009-byte fixture is again rejected. Five real-runtime tests
exercise code, documentation and JSON edits, duplicate evidence and draft intents;
unit regressions reject altered/oversized excerpt references and conflicting IDs.
Cross-repository delivery evidence belongs in the [canonical autonomy receipt](https://github.com/subactor/docs/blob/main/architecture/analysis/autonomy-execution-receipt.md).

### PLF-13887 Core expansion repair

On 2026-09-10 the deployed SubLLM 906a7286cfda4a56f0e422ef78993e650a047a2f
failed before model selection with `code2dsl expanded output exceeds extraction budget`.
A read-only reproduction on Core produced 91,940,009 bytes of canonical JSON,
7,774,381 compressed bytes and 66,962 records (66,825 unique). Deduplication
still leaves 91,778,047 bytes, so duplicate removal does not solve this case.
Historical ticket-062 raised the explicit expanded JSON cap to 128 MiB; ticket-063 below supersedes that increase. The 16 MiB transport,
64 MiB source snapshot, per-file limits and all model query budgets remain unchanged.
Bounded decompression still rejects oversized and concatenated compressed payloads.
Measurement receipt: `receipt:sha256:6948e8a73a33724b5ebcfb8d3e9fbbb6b11f0d2941c0066f4de2f13c09bfae41`.
This is an extraction repair; it does not establish successful editing, publication
of the target task, deployment or global autonomous readiness.

### PLF-13849 extraction transport repair

On 2026-09-10, PLF-13849 remained failed after three attempts with
`code2dsl output exceeds extraction budget`. Reproduction on todo2code PR #119
at `1e986f8953ba21973c6b68c914db8db149b8949a` produced 31,820,078 JSON bytes
with the earlier code-only bridge. The current bridge also extracts documentation
and configuration: its complete envelope measured 41,045,212 bytes in normalized
JSON, compressed to 3,717,450 bytes, with 30,723 unique records across 555 files.
No warnings were returned. Source/build pins are recorded in the receipt above.

Ticket-057 uses gzip only for the private bridge-to-Python transport. Canonical
records, bounded source excerpts, generation evidence, warnings and conflicting-ID
checks are preserved. The transport remains capped at 16 MiB. A separate explicit
64 MiB expanded-JSON cap bounds decompression, including concatenated gzip members;
invalid streams and over-budget outputs fail closed. This increases the supported
expanded local evidence size from 16 to 64 MiB. Source snapshot limits, model query
pages, selection limits, timeouts and attempts are unchanged. This does not eliminate
the extractor's own in-memory allocation before serialization.

The ticket originally bound PR #119 to `0208cb7c0244a7dfec28fd947b8f2041c24737f1`.
The newer PR head had successful `koru / code-review` and verification checks during
this readback. Reopening the old repair requires current-head reconciliation; passing
extraction alone does not mean that the repair ticket ran or the PR was merged.

The deployed extractor `89e72ce` passes four of five current real-runtime tests but
fails the preallocated untracked configuration case. The explicit-input API needed
by the previously merged SubLLM ticket-056 is still in upstream todo2code PR #118.
That dependency gap is separate from compressed extraction and must be resolved
before claiming full production integration.

<!-- docs:section purpose -->
## Purpose

Replace lexical prompt-to-path matching and whole-file Aider attachments with a semantic query over canonical `code2dsl` evidence. Ordinary words such as `tests`, `docs` and Polish `testów` no longer expand directories. This implementation is based on the source revision in metadata; the initial changes belong to ticket-053; the v2 edit contract and response repair belong to ticket-054.

<!-- docs:section scope -->
## Scope

SubLLM owns the `onedev-agent/code-context` selection route and the `onedev-agent/code-edit` editing route. Both use the central coding model candidates and the existing completion/failover policy. An explicitly selected provider remains an allowlist. The canonical extractor remains `autogrammar/todo2code`'s public `code2dsl` API, emitting validated `t2c.intent/v1` records; this adapter does not copy its parsers or introduce a replacement code DSL.

This delivery supports Python and JavaScript/TypeScript (including JSX/TSX), canonical documentation records from `docs2dsl`, and configuration records from `config2dsl`. It changes the existing `subllm-code-edit` implementation and keeps its result envelope and `--aider-bin` compatibility argument. Aider is no longer launched. The outer coding worker continues to own ticket scope validation, repository checks, commits and protected publication.

<!-- docs:section evidence -->
## Evidence

A live synthetic canary on 2026-09-09 used Z.AI GLM-5.3 for both selection and editing. The fixture had 51 tracked files and an `auth.py` of 300,033 bytes. The selection payload contained 1,638 UTF-8 bytes; the editing payload contained 1,763 bytes, including the task and DSL records. These measurements exclude the short system instructions. The model changed `allow(user)` to reject `None`; local assertions checked both `None` and an empty dictionary and verified all 15,000 unrelated padding lines remained unchanged. Execution took 21.19 seconds. This is a synthetic canary, not a production ticket execution receipt.

The private canary receipt is bound by its SHA-256 in metadata. It contains model names, request sizes and digests, selected IDs, source/build pins and before/after source digests; it does not contain credentials or raw LLM transcripts. The initial validation passed 253 tests on Python 3.11, 3.12 and 3.13. The final suite separates 251 hermetic tests in `./scripts/verify` from two real-runtime integration tests in `./scripts/verify-code2dsl`; neither suite skips tests. The integration command fails without all three runtime pins. Lint, bytecode compilation, wheel and sdist builds also passed. The packaged wheel contains the Node bridge. The required OneDev profile runs the hermetic suite. Its image does not include the pinned external todo2code runtime; the two real-runtime tests are separately observed local integration evidence, not claimed as deployed CI coverage. Regression tests cover semantic selection across large inventories, paged reduction, invalid model IDs, path boundaries, stale source, digest mismatches, overlapping edits, truncated excerpts, Python syntax, real Python/JS extraction and preserved operator ignore rules.

<!-- docs:section content -->
## Content

1. Inventory tracked and nonignored untracked eligible source files and copy them into a private temporary snapshot. Exclude hidden paths, dependency caches, symlinks and binary data. Preserve `.gitignore`, `.dockerignore`, `.intentignore` and the operator's Aider ignore policy. Neither source import nor extraction executes repository code.
2. Verify the explicitly configured todo2code source SHA and independent runtime build digest. The build digest covers executable JavaScript, Python helpers, TypeScript parser files and the runtime package metadata. Call `code2dsl` through the packaged Node bridge without credentials, `.env` loading, caches or an LLM in extraction.
3. Send paged DSL projections to the registered selection LLM. When detailed inventory exceeds four page budgets, first ask the same LLM to select files from structural projections of their canonical records (paths, kinds, symbols and record counts); only then query detail pages for the chosen files. Every inventory file is represented; task prose never drives path matching. These contain source IDs/ranges, symbols, semantic statements and metadata; selection does not receive `rawExcerpt` or source file buffers. Identical repeated canonical facts are coalesced; conflicting records with the same ID remain an extraction error. Validate every returned ID against its exact page. If necessary, ask the LLM to reduce the candidates in bounded additional passes. There is no regex/path fallback.
4. For selected records, use the canonical DSL's bounded node excerpts for editing. A record is editable only when its excerpt covers the complete source range, is at most 2,000 characters, and is not a module summary. Incomplete records can provide context but cannot replace unseen code. This is intentionally different from attaching every selected source file. Small nodes may naturally contain all code in a very small file.
5. The editing LLM returns record IDs, original file hashes and replacements for those exact line ranges. Validate every edit, reject unknown IDs and overlapping ranges, check Python syntax, and reobserve source bytes before writing. Preserve all bytes outside selected ranges and preserve file modes. Replace individual files atomically; the outer worktree/lease remains responsible for excluding concurrent writers and for recovery after interruption.
6. Return a secret-free `subllm.dsl-edit-receipt/v1` inside the existing result's `response`: extractor pins, query provider/model and byte counts, request digests, selected record IDs and edit digests. A receipt is evidence of local edits, not merge or deployment authority.

Configure the trusted worker environment with all three values. Run `./scripts/verify-code2dsl` with the same pins to verify real extraction and ignore-policy preservation; missing runtime configuration is an error, never a skip:

```text
SUBLLM_CODE2DSL_RUNTIME=<absolute path to the verified todo2code runtime>
SUBLLM_CODE2DSL_SHA=<40-character source commit>
SUBLLM_CODE2DSL_BUILD_SHA256=<independently approved build digest>
```

The observed canary runtime source was `89e72ce991e3f2518b323d2d5e45ff7368b46acf`, with build digest `0dbae665d10b325fc78d7a9133d8e2efb7f818b68b9c3b9f802a0e2ed1937842`. The digest algorithm is `subllm.code_context.runtime_digest`. Computing a digest is an observation; operators must bind it to independently reviewed build provenance rather than trusting a candidate runtime to approve itself. No sibling-directory discovery or automatic unpinned runtime fallback exists.

### Production inventory follow-up

PR #55 was independently merged at `7ac58f2c95d7749cb3e2557312e9c3c0842d0985` and activated on 2026-09-10 with central provider routing. The systemd fixture passed, including one corrective edit request after an empty plan. Real production task PLF-13811 then exposed 43 identical repeated canonical facts in observability and a 120-page detailed inventory. Ticket-055 adds exact record coalescing and budget-triggered semantic file selection. These observations do not establish completion of PLF-13811.

### Cursor model failover

Production initially lacked the declared optional Cursor SDK dependency. Installing pinned `cursor-sdk` 1.0.31 restored the transport, and live SDK observation showed Sol had exhausted its usage allowance while Grok remained usable. The worker now returns a closed, secret-free model-run failure envelope; the client tries the next registered model before abandoning the provider. A live central-route canary observed Sol `model_unavailable` followed by Grok success. Provider/transport failures retain their existing circuit breaker. No spend limit or provider authority was changed.

### Draft configuration context

A production worker preallocates its governance ticket as untracked Markdown/JSON. The adapter now includes nonignored source drafts in its private snapshot and passes explicit configuration paths to the canonical `config2dsl` API. This requires the upstream explicit-input implementation from todo2code PR #118 (ticket-097); the old runtime at `89e72ce` does not provide this option. Operator ignore rules, path/symlink checks and source-size limits continue to apply.

A selected JSON file aggregate can authorize an operation adding an absent top-level field, such as a draft intent delivery block. Existing properties still require their own selected field records. Local application rechecks absence and original file hash; the operation grants no publication authority.

### Edit plan v2

The v2 synthetic canary on 2026-09-10 passed through the central route using OpenRouter `z-ai/glm-5.3`: it patched a large Python function without changing padding, updated a documentation statement and a JSON field while preserving an unrelated field, and created a passing unittest file. Selection and editing payloads were 5,654 and 6,871 bytes respectively. Receipt: `receipt:sha256:a42fe653ef432a24b31266c84f80ee0876259ae6da21da5bb0ea8dc86e0f79a4`. This is live model integration evidence, not a production queue task or protected merge receipt. The v2 hermetic suite contains 261 tests; real-runtime integration contains three tests.

Both selection and editing requests carry a closed JSON response schema. Invalid JSON or an invalid edit plan receives one corrective request within the original deadline. Whole-plan dry-run validation happens before any source mutation; the error code, without the rejected model response, accompanies the correction. Invalid selection IDs receive one bounded selection correction. Transport failover retains the central circuit breaker.

The model returns `subllm.edit-plan/v2` with `summary` and four operation lists: `edits` (complete node ranges), `patches` (an exact unique `before` substring of the canonical excerpt and its `after` text), `creates` (absent relative path plus new content), and `json_updates` (selected configuration ID, file hash, property-name pointer and typed value). There are at most 32 operations. Every existing-file operation names a selected record and its original file SHA-256. JSON updates cannot escape the selected top-level field or overlap one another; text and JSON operations cannot mix on one file.

The local interpreter validates the whole plan before writing, rechecks original bytes and path boundaries, and validates Python, JSON and TOML syntax. New paths honor Git and operator ignore rules, reject hidden/dependency/symlink paths, and use exclusive no-clobber creation. JSON is serialized locally: original file buffers are never sent as attachments. Multi-file application remains non-transactional across a crash; the governed worktree and outer tests own recovery. YAML and JavaScript syntax/semantics still require repository validation.

The actual code2dsl/docs2dsl/config2dsl integration test covers large-node patching, a documentation statement, a JSON field and a new Markdown file in one plan. Regression tests also cover ambiguous/unseen patches, wrong configuration fields, ignored/existing creation paths, whole-plan syntax rejection, duplicate JSON keys, non-finite numbers and the two-attempt response limit.

<!-- docs:section limitations -->
## Limitations

The canonical facades provide structural facts and bounded excerpts, not a lossless representation of arbitrary source. A large node can now receive an exact substring patch backed by its canonical excerpt; unseen text cannot be patched. Documentation edits cover statements emitted by `docs2dsl` (headings and qualifying references); prose omitted by that extractor remains unavailable. JSON configuration updates stay under a selected top-level field. TOML/YAML text edits require a canonical declaration. Unsupported languages remain unavailable. Creating new files is independent of existing records, but only within the declared extension/path/ignore boundary and the outer worker ticket scope. Source extraction is bounded separately (20,000 source files, 8 MiB per file, 64 MiB total). Query pages are bounded to 48,000 bytes, with at most 128 pages and 32 final selected records. These are operational bounds, not claims about any model's context window.

LLM selection is advisory and can omit a relevant dependency. If it produces no supported edit, execution fails explicitly. Hash/range checks prevent stale or out-of-range application; they do not prove semantic correctness. Full repository tests and independent publication checks remain necessary. Python, JSON and TOML syntax is checked locally; other supported languages still rely on the outer repository's tests. Multi-file application is not crash-atomic. The initial adapter at `2037e7b` was activated on 2026-09-09 with the pinned todo2code runtime; a systemd canary verified a 300,033-byte source file using a 1,730-byte editing payload. All four obsolete PLF attempts were subsequently canceled against observed source publication. That is a deployment observation for v1, not evidence of v2 activation or a new production ticket execution.

<!-- docs:section next_actions -->
## Next actions

For each release, publish through the independent local Validator, bind its exact source and the three canonical runtime pins in the coding worker, and verify a controlled production ticket through tests and protected merge. Update the existing startup source/digest check together with PYTHONPATH; preserve unrelated startup guards. Configure `CODING_AGENT_SUBLLM_PROVIDER` as empty for the central multi-provider policy; an explicit nonempty value intentionally restricts the provider. Coding requests use the supported `SUBLLM_ATTEMPT_TIMEOUT_SECONDS=120` and `SUBLLM_SLOW_RESPONSE_SECONDS=120` settings to avoid a successful selection response immediately cooling down the editing provider. Transport failures retain the central circuit breaker and bounded failover; malformed JSON gets one corrective request within the original deadline, without replaying the malformed response.
