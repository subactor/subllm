---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "cli-provider-fallback",
  "kind": "analysis",
  "version": 1,
  "title": "Subscription CLI providers as fallback while API quotas are exhausted",
  "status": "proposed",
  "owner": "subactor/subllm",
  "created": "2026-10-28",
  "updated": "2026-10-28",
  "review_after": "2026-11-04",
  "source_revision": "f23f8ea4709c0d1226d2721ce340f69e669f2d30",
  "affected_repositories": [
    "subactor/subllm"
  ],
  "evidence": [
    "repo://subactor/subllm/f23f8ea4709c0d1226d2721ce340f69e669f2d30/src/subllm/policy.py",
    "repo://subactor/subllm/f23f8ea4709c0d1226d2721ce340f69e669f2d30/src/subllm/cline_cli.py",
    "repo://subactor/subllm/f23f8ea4709c0d1226d2721ce340f69e669f2d30/subllm.toml"
  ]
}
---

# Subscription CLI providers as fallback

<!-- docs:section question -->
## Question

On 2026-10-28 the SubLLM usage panel (`127.0.0.1:8788`) showed repeated
`SUBLLM-PROVIDER-RATE-LIMIT` errors for `zai glm-5.3` on `supervisor/assessment`,
`koru-agent/nl-to-koru-dsl`, `subactor-proxy/completion` and `todo2code/semantic`.
Which other locally available providers (Codex, Claude, Antigravity, Cline,
Cursor) can serve these routes, and why were they not used?

<!-- docs:section scope -->
## Scope

Local Linux host, Oct 2026. Covers provider reachability, the route candidate
lists produced by `export_routing_contract`, and the operator configuration that
selects the policy file. It does not change `policy.py`, add Cline or `codex-cli`
to default routes, or change credentials.

<!-- docs:section method -->
## Method

Each CLI received the prompt `Reply with exactly: OK` with a 90 s limit, run in
parallel. Candidate lists were exported with the repository policy and with a
copy of it that enables `claude-cli` and `agy-cli`. The overlay was then exercised
through `subllm.complete()` and observed in `/v1/usage`.

<!-- docs:section evidence -->
## Observed

| Provider | Result | Time |
|---|---|---|
| `claude -p` | OK | 10 s |
| `codex exec` | OK (ChatGPT login) | 19 s |
| `agy -p` | OK | 24 s |
| `cline --json -p` | OK (DeepSeek v4.1 flash) | 38 s |
| `cursor-agent -p` | authentication required | 4 s |

Direct API state: Z.AI weekly quota exhausted until 2026-10-30 15:27; Gemini API
returns 402 `RESOURCE_EXHAUSTED` (prepay credits depleted); OpenRouter reported
402 insufficient credits earlier the same day. `OPENAI_API_KEY` and
`ANTHROPIC_API_KEY` are empty, so the `codex` and `claude` API providers are
skipped.

With `subllm.complete()` and the overlay policy, `koru-agent/nl-to-koru-dsl` and
`supervisor/assessment` were answered by `claude-cli` / `claude-sonnet-5` in about
4.5 s. After restarting the supervisor with the overlay, its first call was served
by `claude-cli` with no preceding Z.AI error.

<!-- docs:section facts -->
## Cause

The default routes list `agy-cli` and `claude-cli`, but providers missing from
`subllm.toml` stay disabled. The tracked `subllm.toml` enables `codex-cli` only,
and `codex-cli` is a candidate only on the coding route. Setting
`SUBLLM_PROVIDER_ORDER` therefore cannot add CLI transports to the default routes.
Z.AI has the lowest priority number, so it is tried first on every call.
`cline-cli` has a transport (`cline_cli.py`) but no provider entry in `policy.py`.

<!-- docs:section hypotheses -->
## Interpretation

Ollama failures of 30-45 s (`PROVIDER-UNAVAILABLE`) look like intermittent GPU
contention while the 30B model is loaded, not an endpoint fault; this was not
reproduced in isolation.

<!-- docs:section limitations -->
## Limits

The overlay is an operator file, not a tracked policy:
`~/.local/share/subllm/operator-policy/cli-fallback-20261028.toml`, selected
through a systemd drop-in named `*-cli-fallback-20261028.conf`. It was applied to
`subactor-supervisor`, `willman-hub`, and the koru lanes. Restarted so far:
supervisor and four koru lanes. `willman-hub` was busy (3/3 workers) and was not
restarted. `c2004-koru-autonomous` was excluded because its venv ships an older
subllm that rejects extra providers. Subscription quotas of Claude, ChatGPT and
Antigravity were not measured; background loops now consume them.

The tracked change was blocked by the work-start controller (`SERIALIZE`): the
`application` workstream is at its limit of three active tickets (145, 150, 168).
No limit was waived.

<!-- docs:section recommendations -->
## Recommendations

1. When an `application` slot is free, enable `claude-cli` (priority 5) and
   `agy-cli` (priority 8) in `subllm.toml` and demote Z.AI and the Gemini API
   while their quota/credits are exhausted. Priorities must stay unique after
   adding route offsets. Restore the Z.AI position after 2026-10-30 15:27.
2. Add `codex-cli` and `cline-cli` as candidates in `policy.py` default routes.
3. Replace the operator overlay with the tracked file and remove the drop-ins.
4. Log in to Cursor (`agent login`) before relying on `cursor-cli`.
5. Restart `willman-hub` and `c2004-koru-autonomous` when idle and upgrade the
   latter's subllm.

