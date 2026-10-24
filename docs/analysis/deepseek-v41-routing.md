---
{
  "schema": "wellmanifest.docs/document/v1",
  "id": "deepseek-v41-routing",
  "kind": "analysis",
  "version": 1,
  "title": "DeepSeek V4.1: task cost, latency and SubLLM backlog",
  "status": "proposed",
  "scope": "repository",
  "owner": "subactor/subllm",
  "created": "2026-10-24",
  "updated": "2026-10-24",
  "review_after": "2026-10-25",
  "source_revision": "a367cf701de4b7aa758f47029a9cdfe94ca7ed88",
  "affected_repositories": ["subactor/subllm"],
  "evidence": [
    "repo://subactor/subllm/a367cf701de4b7aa758f47029a9cdfe94ca7ed88/src/subllm/adaptive.py",
    "repo://subactor/subllm/a367cf701de4b7aa758f47029a9cdfe94ca7ed88/src/subllm/policy_config.py"
  ]
}
---

# DeepSeek V4.1: task cost, latency and SubLLM backlog

<!-- docs:section question -->
## Which route should a task select?

There is no single cheapest DeepSeek route for every task. Prompt-heavy work,
generation-heavy work and cache-heavy work have different winners. The public
OpenRouter inventory observed on 2026-10-24 around 19:01 UTC exposes prices but
no recent latency or throughput measurements for these models. A price winner
therefore cannot yet be called the fastest or available to this account.

<!-- docs:section scope -->
## Scope and ownership

This report covers SubLLM's nine previously open issues, public DeepSeek V4.1
endpoint metadata and the bounded changes in native tickets128–130. It does
not assert fleet deployment, provider quality equivalence, funded account
access or trusted merge approval. Existing Gemini role preferences stay intact;
the requested Gemini 3.8 Flash remains the advisory model. Ollama is excluded
from the availability comparison.

<!-- docs:section method -->
## Reproducible comparison

Acquire the two public endpoint documents independently, preserve their bytes
and observation time, and compare the exact requested model identifier:

- [Mutable Flash alias endpoints](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4.1-flash/endpoints).
- [Flash 1017 snapshot endpoints](https://openrouter.ai/api/v1/models/deepseek/deepseek-v4.1-flash-1017/endpoints).

Compute text cost in USD from per-token prices:
`(input - cached) * prompt + cached * cache_read + output * completion + request`.
The endpoint prices already include the advertised discount: multiplying by
the discount again understates cost. Preserve distinct model snapshots and
quantizations; price alone says nothing about their relative quality.

The new `subllm.openrouter_routing.rank_endpoints()` helper accepts these
caller-acquired documents and explicit token estimates. It rejects stale or
future observations, wrong model bindings, unavailable endpoints, unsupported
parameters, insufficient token limits and quotes above the task budget.
It performs no discovery request during completion. A positive time penalty
ranks measured endpoints first; a hard TTFT bound excludes unknown latency.
These estimates guide selection and do not replace server or caller deadlines.

```python
from subllm.openrouter_routing import rank_endpoints

ranked = rank_endpoints(
    snapshot, model="deepseek/deepseek-v4.1-flash",
    observed_at=observed_epoch, now=current_epoch,
    input_tokens=10_000, output_tokens=10_000,
    max_age_seconds=900, max_cost_usd="0.01",
    required_parameters=("tools",),
)
```

<!-- docs:section evidence -->
## Observed prices and evidence

USD per million text tokens; selected endpoints from the timestamped API,
not a guarantee that the same prices or providers persist:

| Model | Endpoint tag | Input | Output | Cached input |
| --- | --- | ---: | ---: | ---: |
| Flash alias | open-inference/fp4 | 0.0200 | 1.0000 | 0.015000 |
| Flash alias | baidu/fp8 | 0.0537 | 0.2148 | 0.001074 |
| Flash alias | relace | 0.0700 | 0.5000 | 0.008000 |
| Flash alias | decart/fp4 | 0.0900 | 0.1800 | 0.018000 |
| Flash alias | deepinfra/fp8/flex | 0.1120 | 0.3360 | 0.003360 |
| Flash alias | deepinfra/fp8 | 0.1400 | 0.4200 | 0.004200 |
| Flash 1017 | open-inference/fp4 | 0.0200 | 1.0000 | 0.015000 |
| Flash 1017 | relace | 0.0700 | 0.5000 | 0.008000 |
| Flash 1017 | deepinfra/fp8/flex | 0.0784 | 0.2352 | 0.002352 |
| Flash 1017 | deepinfra/fp8 | 0.0980 | 0.2940 | 0.002940 |
| Flash 1017 | sail-research/fp4 | 0.1010 | 0.1500 | 0.006735 |
| Flash 1017 | baidu/fp8 | 0.2800 | 1.1300 | 0.006000 |

The alias contained 41 endpoints and the snapshot 34. All recent latency and
throughput fields were null. Public status/uptime describes advertised
endpoints; successful authenticated inference remains a separate observation.
The private API receipts and deterministic quote comparison are digest-bound
in the Report sidecar. This is text-token accounting; image/tool/search charges
or unadvertised fees require separate estimates.

[Official direct DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/)
advertised Flash off-peak input miss/cache hit/output of $0.15/$0.003/$0.60 per
million tokens, versus $0.30/$0.006/$1.20 at peak. Peak windows were weekdays
01:00–04:00 and 06:00–10:00 UTC. These are direct-API terms, not OpenRouter
terms. Direct-provider credentials, account access and local latency were not
validated by this work.

<!-- docs:section facts -->
## Token mix changes the winner

Examples without cache, among eligible advertised endpoints:

| Input / output tokens | Flash alias winner / task USD | Flash 1017 winner / task USD |
| --- | --- | --- |
| 100,000 / 1,000 | Open Inference / 0.003000 | Open Inference / 0.003000 |
| 10,000 / 10,000 | Baidu / 0.002685 | Sail / 0.002510 |
| 1,000 / 100,000 | Decart / 0.018090 | Sail / 0.015101 |

Baidu is not universally the cheapest output route. The observed Decart alias
and Sail snapshot output prices were lower. Comparing alias Baidu with snapshot
Sail also changes the model version; select quality and task capability before
ranking cost. The user-supplied DeepInfra and Relace figures are insufficient
to identify a universal winner across snapshots.

## Backlog reconciliation

These were the nine open GitHub issues before this session. Source presence
and old ticket status are not evidence of every consumer's runtime adoption.

| Issue | Observed source/delivery | Remaining acceptance |
| --- | --- | --- |
| [128](https://github.com/subactor/subllm/issues/128) | Reproduced sibling-policy inheritance; native ticket130 fixes it with provenance, explicit scope and defaults-only controls. | Exact-head protected publication of the repair. |
| [124](https://github.com/subactor/subllm/issues/124) | Code-context/progress source delivered through PR125. | Correlated live consumer execution and host-scoped rollout. |
| [84](https://github.com/subactor/subllm/issues/84) | Usage, MCP and PolicyBus transport source exists. | Verify remaining consumer adapters and actual telemetry delivery. |
| [72](https://github.com/subactor/subllm/issues/72) | Docs/Report checks are invoked by `scripts/verify`; this new analysis requires its tracked Report sidecar. | Confirm complete protected coverage/canary before closing the wider issue. |
| [71](https://github.com/subactor/subllm/issues/71) | Historical continuation references a legacy checkout. | Observe its owner, dirty state and unique history before any cleanup. |
| [59](https://github.com/subactor/subllm/issues/59) | Versioned routing contract, CLI export and tests exist. | Verify exact consumer pins and live readback. |
| [42](https://github.com/subactor/subllm/issues/42) | Multiple code-edit routes exist. | Actual executor access and funded fallback availability; catalog presence alone is insufficient. |
| [24](https://github.com/subactor/subllm/issues/24) | Python catalog and TOML configuration remain. | Full typed catalog-authoring migration; the new bounded JSON controls cover only one provider. |
| [20](https://github.com/subactor/subllm/issues/20) | Source version has advanced to 1.14.0. | Verify registry publication and consumer consolidation; version text alone does not close it. |

New GitHub issue [130](https://github.com/subactor/subllm/issues/130) tracks the
DeepSeek implementation in native ticket128. Native ticket129 owns this
research. GitHub issue numbers and native ticket numbers are distinct.

The preceding native availability audit received successful responses from
Gemini 3.8 Flash, 3.6 Flash, 3.7 Flash Medium, 3.5 Flash Lite and 3.1 Pro High
through agy, plus GPT-5.6 Sol/Luna through the installed Codex CLI. OpenRouter
returned HTTP402, ZAI429 and the tested old Gemini2.5 routes404. These dated
observations do not guarantee continued access. No account cooldown was reset,
credit purchased or shared provider configuration changed.

<!-- docs:section hypotheses -->
## Scheduling and latency hypotheses

Cache-heavy batch work may favor direct off-peak DeepSeek; output-heavy work
may favor the cheaper OpenRouter snapshot endpoint. Neither hypothesis proves
local speed. Network ping omits model queueing and first-token delay. Measure
streaming TTFT, total duration, output throughput, failures and billed tokens
under the same prompt size, requested capabilities and exact model snapshot.
Use repeated bounded samples and p50/p90/p99; retain unknown until observed.

The existing adaptive path already uses cached account health, class-compatible
priority and bounded failover. Preserve those guards. A402 should suppress
account-wide paid retries until the normal cooldown expires; trying every
endpoint with the same unfunded account does not provide useful latency data.

<!-- docs:section limitations -->
## Limits and rollout boundary

Source tests cover task cost, cache/request accounting, freshness, capability
and context guards, missing latency and propagation into the native worker.
The new helper does not run a continuous benchmark or automatically spend on
provider probes. Its estimates are not hard end-to-end latency guarantees.
The optional provider parameters are applied in native SDK/proxy completions;
no claim is made that every external LiteLLM export gains these controls.
Protected review, merge, package publication and service activation retain
separate evidence. An initial advisory Gemini request timed out. A smaller Gemini 3.8 Flash
request with an explicit attempt deadline succeeded in 8.73 seconds; it
highlighted TTFT versus total duration, sampling bias and provider volatility.
This advice supplied no independent approval.

<!-- docs:section recommendations -->
## Bounded operation and next actions

Start with an opt-in policy file outside Git. Select exact wire model names;
retain Gemini for existing roles. The policy must be absolute, bounded JSON
with schema `subllm.openrouter-routing/v1`:

```json
{
  "schema": "subllm.openrouter-routing/v1",
  "models": {
    "deepseek/deepseek-v4.1-flash": {
      "sort": "price",
      "only": ["baidu/fp8", "decart/fp4", "relace"],
      "max_price": {"prompt": 0.10, "completion": 0.60},
      "preferred_max_latency": 2,
      "max_tokens": 4096,
      "allow_fallbacks": false,
      "require_parameters": true
    }
  }
}
```

Set `SUBLLM_OPENROUTER_POLICY_FILE` for that request context and call the new
`subactor-proxy/deepseek-flash` route or explicit catalog model. Existing tighter
output caps remain tighter. Conflicting provider constraints fail closed.
[OpenRouter routing controls](https://openrouter.ai/docs/guides/routing/provider-selection)
include soft latency preferences; keep SubLLM's caller/attempt deadlines as the
actual timeout boundary. Hard quote budgets and endpoint selection should use
a fresh snapshot, then an explicit allowlist; an empty ranking must not weaken
the budget or silently switch model.

Before production selection, restore normal account availability and run a
small, capped streaming benchmark of the chosen same-snapshot candidates.
Record region, quantization, errors, cache and billed cost. Reuse issues42/84
for executor access/telemetry and issue24 for full catalog migration. Close
issues only after their remaining acceptance has evidence; preserve the legacy
checkout until its independent owner and data are known.
