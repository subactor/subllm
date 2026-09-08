---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "codex-cli-integration",
  "kind": "analysis",
  "version": 1,
  "title": "Local Codex CLI through SubLLM",
  "status": "proposed",
  "owner": "subactor/subllm",
  "created": "2026-09-08",
  "updated": "2026-09-08",
  "review_after": "2026-09-22",
  "source_revision": "8a89fb1ee8b017dc405ecb3c83277984bf7fc6ba",
  "affected_repositories": [
    "subactor/subllm"
  ],
  "evidence": [
    "repo://subactor/subllm/8a89fb1ee8b017dc405ecb3c83277984bf7fc6ba/src/subllm/codex_cli.py",
    "repo://subactor/subllm/8a89fb1ee8b017dc405ecb3c83277984bf7fc6ba/tests/test_codex_cli.py"
  ]
}
---

# Local Codex CLI through SubLLM

<!-- docs:section question -->
## Result

The Python `complete()` API now supports local Codex through the explicit
`organism-guard/refactor` route and `codex-cli` transport. A real invocation
using installed Codex 0.153.4 and its existing ChatGPT login succeeded.
This is a local installation and source branch, not protected publication.

<!-- docs:section scope -->
## Ownership and compatibility

`policy.py` remains the provider/model/application/route owner. `subllm.toml`
remains the operator configuration. The existing `codex` provider still means
OpenAI API with `OPENAI_API_KEY`; existing coding routes are unchanged.
The new route contains only `codex-cli`, with model `gpt-5.6-sol` selected by
policy. It has no network-provider fallback. Package build: `1.9.0+codex.1`.

The adopted credential-strategy pack still describes API credentials. CLI-owned
login is explicitly outside that pack; no credential shape, API base or API key
is fabricated for it. Credential enumeration excludes the empty CLI credential
field. Prior operator configurations missing the new provider remain valid and
keep that provider disabled until explicitly configured. The new repository
configuration enables it, but only the new exact route selects it.

<!-- docs:section method -->
## Invocation

```python
from subllm import complete
result = complete(
    "organism-guard", "refactor",
    [{"role": "user", "content": "Reply exactly OK. Do not use tools."}],
    timeout_seconds=120,
)
```

Operator configuration must enable `codex-cli`. An existing provider allowlist
may exclude it; set `SUBLLM_PROVIDER_ORDER=codex-cli` for this explicit route.
For longer coding tasks set `SUBLLM_ATTEMPT_TIMEOUT_SECONDS=120` as well as the
caller's total budget. The default per-attempt policy is still 12 seconds.
A CLI error fails closed without automatic retry of the same editing request.

The executable must be available on PATH and already logged in. Route resolution
checks executable availability only; it does not claim successful authentication.
The real invocation verifies actual login/model access. No auth file is opened
by SubLLM. No new shell/HTTP endpoint or POA process was introduced: this extends
the existing Python completion transport, not the PolicyBus process catalog.

<!-- docs:section evidence -->
## Observed verification

- `./scripts/verify`: Ruff, compileall, 233 pytest tests and sdist/wheel build PASS.
- Tests cover fixed arguments, credential exclusion, missing binary, timeout with
  descendant cleanup, nonzero exit, incomplete/failed events and explicit routing.
- Live smoke: `codex-cli`, `gpt-5.6-sol`, exact expected answer, 7586 ms total;
  reported usage 13155 input / 9984 cached input / 5 output tokens.
- Guard's real NL intent refactoring: 30174 ms completion, 24746 input and
  708 output tokens. Exact candidate subsequently passed the target validator.
- An initial smoke failed before execution because the inherited credential-file
  allowlist excluded the new provider. Explicit local selection fixed the input;
  no shared credential file or shared operator configuration was changed.

Evidence: private receipts under `.subactor/receipts/codex-cli-20260908/`;
source code and this bounded report are the tracked deliverables. Raw response
and command transcripts remain outside Git. Public Codex command behavior was
checked against [OpenAI documentation](https://learn.chatgpt.com/docs/non-interactive-mode)
and local `codex exec --help`.

<!-- docs:section facts -->
## Transport boundary

A fixed argv runs `codex exec` with explicit model, ephemeral session, empty
private working directory, read-only sandbox selection, ignored user config,
disabled shell-tool/multi-agent features, JSONL events and final-message file.
Prompt data goes through stdin, never shell interpolation. No arbitrary argv,
repository working directory or generic shell command is accepted.

The child gets a minimal environment without provider API keys. Codex retains
its own HOME/CODEX_HOME login. Output is capped at 1 MB and one successful terminal
turn is required. Timeout/error kills and reaps the process group. Only known
nonnegative usage counters are returned, with a completion attempt receipt.
LiteLLM export of this transport is rejected instead of inventing an API model.

<!-- docs:section hypotheses -->
## Performance interpretation

The CLI's system context adds overhead: even the small smoke prompt reports
13155 input tokens. One successful code generation does not prove a general
speed advantage over remote direct completions or guarantee account availability.

<!-- docs:section limitations -->
## Limits

The supported tested host is Linux, Codex 0.153.4, Python 3.13.12. A locally
installed CLI still calls a remote model. CLI options and account access can
change. This is not an adversarial-code VM or a protected execution identity;
no claim of full host isolation follows from the empty directory or venv.

The pinned Wellmanifest/docs checker passed (2 managed documents, zero findings).

Source changes live on `ticket/048-codex-cli-integration`. They have not been
pushed, independently validated for merge, merged or deployed to fleet services.
The protected OneDev/Validator publication path was not invoked. Formal fleet
adoption and Strategy execution binding remain separate tasks.

<!-- docs:section recommendations -->
## Operation

Use explicit routes and bounded deadlines. Keep the shared API providers intact.
Before broader rollout, validate the selected Codex version and login in the
actual executor environment, then use the existing protected publication path.
