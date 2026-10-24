"""Opt-in OpenRouter controls and secret-free, task-dependent endpoint quotes.

Quotes consume caller-acquired public metadata; completion never performs a
discovery request. Prices are USD/token and include any advertised discount.
Remote latency percentiles are observations, not local TTFT guarantees.
"""
from __future__ import annotations

import json
import math
import os
import re
from decimal import Decimal, DecimalException, InvalidOperation
from pathlib import Path

from .errors import CompletionError

CODE = "SUBLLM-OPENROUTER-ROUTING"
POLICY_ENV = "SUBLLM_OPENROUTER_POLICY_FILE"


def _fail(message):
    raise CompletionError(message, diagnostic_code=CODE)


def _number(value, *, positive=False):
    if isinstance(value, bool):
        _fail("routing numbers cannot be boolean")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _fail("invalid routing number")
    if not number.is_finite() or number < 0 or (positive and number == 0):
        _fail("routing number must be finite and nonnegative")
    return number


def _tokens(value):
    if type(value) is not int or value < 0:
        _fail("token counts must be nonnegative integers")
    return value


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate routing policy key")
        result[key] = value
    return result


def _controls(row):
    allowed = {"sort", "only", "max_price", "preferred_max_latency",
               "preferred_min_throughput", "max_tokens", "allow_fallbacks", "require_parameters"}
    if not isinstance(row, dict) or set(row) - allowed:
        _fail("unknown OpenRouter routing controls")
    provider = {"require_parameters": True, "allow_fallbacks": False}
    if row.get("allow_fallbacks", False) is not False or row.get("require_parameters", True) is not True:
        _fail("bounded routing requires parameter support and disables uncontrolled fallbacks")
    if "sort" in row:
        if row["sort"] not in ("price", "latency", "throughput"):
            _fail("unknown OpenRouter sort strategy")
        provider["sort"] = row["sort"]
    if "only" in row:
        tags = row["only"]
        if (not isinstance(tags, list) or not 1 <= len(tags) <= 32
                or any(not isinstance(t, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]{0,127}", t) for t in tags)
                or len(set(tags)) != len(tags)):
            _fail("provider only must contain unique endpoint slugs")
        provider["only"] = list(tags)
    for key in ("preferred_max_latency", "preferred_min_throughput"):
        if key in row:
            value = float(_number(row[key], positive=True))
            if not math.isfinite(value):
                _fail("routing preference exceeds supported range")
            provider[key] = value
    if "max_price" in row:
        prices = row["max_price"]
        if not isinstance(prices, dict) or not prices or set(prices) - {"prompt", "completion"}:
            _fail("invalid per-million-token price caps")
        provider["max_price"] = {}
        for key, value in prices.items():
            price = float(_number(value))
            if not math.isfinite(price):
                _fail("price cap exceeds supported range")
            provider["max_price"][key] = price
    cap = row.get("max_tokens")
    if cap is not None and (type(cap) is not int or not 1 <= cap <= 131072):
        _fail("max_tokens must be an integer between 1 and 131072")
    return provider, cap


def apply_parameters(provider, model, parameters, *, environ=None):
    """Restrict an existing request without changing credentials or its model."""
    result = dict(parameters)
    env = os.environ if environ is None else environ
    path = env.get(POLICY_ENV)
    if provider != "openrouter" or not path:
        return result
    try:
        path = Path(path).expanduser()
        if not path.is_absolute():
            _fail("OpenRouter policy path must be absolute")
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            _fail("OpenRouter policy exceeds 65536 bytes")
        policy = json.loads(raw, object_pairs_hook=_pairs)
    except (OSError, ValueError, TypeError) as exc:
        raise CompletionError("cannot load OpenRouter routing policy", diagnostic_code=CODE) from exc
    if (not isinstance(policy, dict) or set(policy) != {"schema", "models"}
            or policy["schema"] != "subllm.openrouter-routing/v1"
            or not isinstance(policy["models"], dict) or len(policy["models"]) > 128):
        _fail("invalid OpenRouter routing policy")
    if model not in policy["models"]:
        return result
    controls, cap = _controls(policy["models"][model])
    if "provider" in result and result["provider"] != controls:
        _fail("existing provider constraints cannot be replaced")
    result["provider"] = controls
    if cap is not None:
        for key in ("max_tokens", "max_completion_tokens"):
            if key in result:
                current = result[key]
                if isinstance(current, str) and current.isdecimal():
                    current = int(current)
                if type(current) is not int or current <= 0:
                    _fail("invalid existing output cap")
                cap = min(cap, current)
                result[key] = cap
        result["max_tokens"] = cap
    return result


def _metric(value, quantile):
    if isinstance(value, dict):
        value = value.get(quantile)
    if value is None:
        return None
    metric = float(_number(value))
    if not math.isfinite(metric):
        _fail("endpoint metric exceeds supported range")
    return metric


def rank_endpoints(document, *, model, observed_at, now, input_tokens, output_tokens,
                   cached_input_tokens=0, max_age_seconds=900, max_cost_usd=None,
                   max_ttft_seconds=None, latency_penalty_usd_per_second="0",
                   required_parameters=(), quantile="p90"):
    """Rank fresh compatible endpoints by estimated task cost and optional time cost.

    A hard TTFT bound requires an observed percentile. A positive time penalty
    puts unmeasured endpoints after measured endpoints, never at zero latency.
    Empty output means no endpoint satisfies the constraints; it is not a
    permission to weaken them or change the requested model.
    """
    age = _number(now) - _number(observed_at)
    if age < 0 or age > _number(max_age_seconds, positive=True):
        _fail("endpoint observation is stale or from the future")
    for count in (input_tokens, output_tokens, cached_input_tokens):
        _tokens(count)
    if cached_input_tokens > input_tokens:
        _fail("cached input exceeds total input")
    if quantile not in ("p50", "p75", "p90", "p99"):
        _fail("unsupported latency quantile")
    data = document.get("data") if isinstance(document, dict) else None
    if (not isinstance(data, dict) or data.get("id") != model
            or not isinstance(data.get("endpoints"), list) or len(data["endpoints"]) > 512):
        _fail("endpoint snapshot must bind the requested model")
    budget = None if max_cost_usd is None else _number(max_cost_usd)
    ttft_cap = None if max_ttft_seconds is None else float(_number(max_ttft_seconds, positive=True))
    if ttft_cap is not None and not math.isfinite(ttft_cap):
        _fail("latency cap exceeds supported range")
    penalty = _number(latency_penalty_usd_per_second)
    ranked = []
    seen = set()
    for endpoint in data["endpoints"]:
        if not isinstance(endpoint, dict) or type(endpoint.get("status")) is not int or endpoint["status"] != 0:
            continue
        tag = endpoint.get("tag")
        if not isinstance(tag, str) or not tag or tag in seen:
            continue
        seen.add(tag)
        supported = endpoint.get("supported_parameters", [])
        if not isinstance(supported, list) or not set(required_parameters).issubset(supported):
            continue
        limits = (("context_length", input_tokens + output_tokens),
                  ("max_prompt_tokens", input_tokens), ("max_completion_tokens", output_tokens))
        if any(endpoint.get(k) is not None and (type(endpoint[k]) is not int or endpoint[k] < n)
               for k, n in limits):
            continue
        try:
            prices = endpoint["pricing"]
            prompt = _number(prices["prompt"])
            completion = _number(prices["completion"])
            cached = _number(prices.get("input_cache_read", prompt))
            request = _number(prices.get("request", "0"))
            cost = ((input_tokens - cached_input_tokens) * prompt + cached_input_tokens * cached
                    + output_tokens * completion + request)
            latency = _metric(endpoint.get("latency_last_30m"), quantile)
            throughput = _metric(endpoint.get("throughput_last_30m"), quantile)
        except (KeyError, TypeError, DecimalException, CompletionError):
            continue
        if budget is not None and cost > budget:
            continue
        if ttft_cap is not None and (latency is None or latency > ttft_cap):
            continue
        elapsed = latency + output_tokens / throughput if latency is not None and throughput else None
        score = cost + penalty * Decimal(str(elapsed)) if elapsed is not None else cost
        ranked.append({"tag": tag, "provider": endpoint.get("provider_name"), "model": model,
                       "estimated_cost_usd": str(cost), "ttft_seconds": latency,
                       "estimated_seconds": elapsed, "latency_quantile": quantile,
                       "score": str(score), "unmeasured": bool(penalty and elapsed is None)})
    return sorted(ranked, key=lambda row: (row["unmeasured"], Decimal(row["score"]), row["tag"]))
