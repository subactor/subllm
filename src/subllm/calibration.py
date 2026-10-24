"""Opt-in fixed-workload calibration. Never called by normal completions.

Run ``python -m subllm.calibration --help``. Budgets reserve advertised cost for
1024 input tokens and the output cap before dispatch. Unexpected/missing billing
stops the campaign; cancelling a socket is not a provider billing guarantee.
TTFT is the first nonempty client-visible content frame; throughput is a
usage/window estimate. Repeated short prompts can be cache-biased. These local
sample quantiles do not predict coding/RAG workloads or production SLOs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import sys
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from .calibration_worker import MESSAGES, RESULT_SCHEMA, result
from .client_workers import _terminate_worker_process_group
from .credential_env import merged_environment
from .errors import CompletionError, SubLLMError
from .health import order_by_health, record_failure, record_success
from .openrouter_routing import _number, rank_endpoints
from .policy import MODELS
from .policy_config import load_policy_config, resolve_attempt_timeout
from .proxy import _build_model_resolved_routes
from .usage import record_attempt

SCHEMA = "subllm.endpoint-calibration/v1"
PROFILE = "fixed-smoke-v1"
INPUT_BOUND = 1024
MODELS_ALLOWED = {"deepseek-v4.1-flash", "deepseek-v4.1-flash-1017"}


def _fail(message):
    raise CompletionError(message, diagnostic_code="SUBLLM-CALIBRATION")


def _digest(snapshot):
    raw = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _invoke(request, endpoint, timeout, *, policy_file=None):
    env = dict(os.environ)
    if policy_file is not None:
        env["SUBLLM_POLICY_FILE"] = str(policy_file)
    source = str(Path(__file__).resolve().parents[1])
    others = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and p != source]
    env["PYTHONPATH"] = os.pathsep.join([source, *others])
    process = subprocess.Popen([sys.executable, "-m", "subllm.calibration_worker"],  # noqa: S603
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=env, start_new_session=True)
    started = time.monotonic()
    try:
        output, _ = process.communicate(json.dumps({"schema": "subllm.calibration-worker-request/v1",
                                                   "request": request, "endpoint": endpoint}).encode(), timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_worker_process_group(process)
        return result("timeout", started)
    except BaseException:
        _terminate_worker_process_group(process)
        raise
    if process.returncode or len(output) > 65536:
        return result("worker_error", started)
    try:
        value = json.loads(output)
        expected = set(result("success", 0))
        if not isinstance(value, dict) or set(value) != expected or value["schema"] != RESULT_SCHEMA:
            raise ValueError("invalid worker result")
        if value["outcome"] not in {"success", "truncated", "stream_error", "incomplete_stream", "stream_limit",
                                    "billing_unknown", "invalid_stream", "transport_error"} and not (
                isinstance(value["outcome"], str) and value["outcome"].startswith("http_")
                and value["outcome"][5:].isdigit() and 100 <= int(value["outcome"][5:]) <= 599):
            raise ValueError("invalid outcome")
        for key in ("ttft_seconds", "first_reasoning_seconds", "total_seconds", "tokens_per_second"):
            if value[key] is not None and (type(value[key]) not in (float, int)
                                           or not math.isfinite(value[key]) or value[key] < 0):
                raise ValueError("invalid timing")
        for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
            if value[key] is not None and (type(value[key]) is not int or not 0 <= value[key] <= 10**12):
                raise ValueError("invalid token count")
        if value["cost_usd"] is not None:
            value["cost_usd"] = str(_number(value["cost_usd"]))
        if value["outcome"] == "success" and any(value[k] is None for k in (
                "ttft_seconds", "input_tokens", "output_tokens", "cost_usd")):
            raise ValueError("success requires timing and accounting")
        return value
    except (ValueError, TypeError, CompletionError):
        return result("invalid_worker_result", started)


def _request_for(route, tag, endpoint, cap, timeout):
    params = dict(route.model_parameters)
    controls = dict(params.get("provider", {}))
    if "only" in controls and not any(tag == t or ("/" not in t and tag.startswith(t + "/"))
                                      for t in controls["only"]):
        _fail("endpoint is excluded by existing provider constraints")
    cap = min([cap, *[int(params[k]) for k in ("max_tokens", "max_completion_tokens") if k in params]])
    prices = {k: float(_number(endpoint["pricing"][k]) * 1_000_000) for k in ("prompt", "completion")}
    for key, old in controls.get("max_price", {}).items():
        prices[key] = min(prices[key], float(_number(old)))
    controls.update(only=[tag], allow_fallbacks=False, require_parameters=True, max_price={**prices, "request": 0})
    params.update(provider=controls, max_tokens=cap)
    if "max_completion_tokens" in params:
        params["max_completion_tokens"] = cap
    return {"schema": "subllm.openai-worker-request/v1", "provider": route.provider,
            "api_base": route.api_base, "wire_model": route.wire_model, "api_key": route.api_key,
            "messages": MESSAGES, "model_parameters": params,
            "request_fields": dict(route.provider_request_fields(request_id=None)),
            "extra_headers": dict(route.extra_headers), "response_format": None, "timeout_seconds": timeout}


def calibrate(snapshot, *, model, observed_at, endpoints, max_cost_usd, samples=1, max_tokens=32,
              timeout_seconds=15, live=False, environ=None, now=None):
    """Reserve before every call. Default dry-run never resolves credentials."""
    now = time.time() if now is None else now
    budget = _number(max_cost_usd, positive=True)
    if model not in MODELS_ALLOWED or budget > 1 or type(live) is not bool:
        _fail("invalid calibration model, live flag or budget (maximum USD1)")
    if type(samples) is not int or not 1 <= samples <= 20 or type(max_tokens) is not int or not 1 <= max_tokens <= 256:
        _fail("samples must be1..20 and output cap1..256")
    if (type(timeout_seconds) not in (float, int) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30):
        _fail("attempt deadline must be positive and at most30 seconds")
    if (not isinstance(endpoints, (list, tuple)) or not 1 <= len(endpoints) <= 8
            or any(not isinstance(t, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]{0,127}", t)
                   for t in endpoints) or len(set(endpoints)) != len(endpoints)):
        _fail("choose1..8 unique explicit endpoints")
    wire = MODELS[model].providers["openrouter"].wire_model
    quotes = rank_endpoints(snapshot, model=wire, observed_at=observed_at, now=now,
                            input_tokens=INPUT_BOUND, output_tokens=max_tokens, max_cost_usd=str(budget))
    candidates = {e["tag"]: e for e in quotes}
    rows = [e for e in snapshot["data"]["endpoints"] if isinstance(e, dict) and isinstance(e.get("tag"), str)]
    metadata = {e["tag"]: e for e in rows}
    if len(metadata) != len(rows):
        _fail("duplicate endpoint identities are ambiguous")
    for tag in endpoints:
        if tag not in candidates or _number(metadata[tag]["pricing"].get("request", 0)) != 0:
            _fail("chosen endpoint has no compatible affordable zero-request-fee quote")
    report = {"schema": SCHEMA, "profile": PROFILE, "model": wire, "snapshot_sha256": _digest(snapshot),
              "observed_at": now, "snapshot_observed_at": observed_at,
              "input_token_bound": INPUT_BOUND, "output_token_cap": max_tokens,
              "budget_usd": str(budget), "reserved_cost_usd": "0", "samples": [],
              "live": live, "stop_reason": "sample_limit", "planned_endpoints": []}
    reserved = Decimal(0)
    route = execution = env = None
    if live:
        env = merged_environment(environ=environ)
        execution = load_policy_config(environ=env)
        routes = [r for r in _build_model_resolved_routes(model, environ=env) if r.provider == "openrouter"]
        if not routes:
            report["stop_reason"] = "route_unavailable"
            return report
        if not order_by_health(tuple(routes), environ=env):
            report["stop_reason"] = "account_cooldown"
            return report
        route = routes[0]
        # Validate every requested constraint before the first paid request.
        for tag in endpoints:
            _request_for(route, tag, metadata[tag], max_tokens, timeout_seconds)
    started = time.monotonic()
    for index in range(samples):
        tag = endpoints[index % len(endpoints)]
        cost = Decimal(candidates[tag]["estimated_cost_usd"])
        if reserved + cost > budget:
            report["stop_reason"] = "budget_limit"
            break
        remaining = 120 - (time.monotonic() - started)
        if remaining <= 0:
            report["stop_reason"] = "campaign_deadline"
            break
        if live and not 0 <= _number(time.time()) - _number(observed_at) <= 900:
            report["stop_reason"] = "snapshot_stale"
            break
        if live and load_policy_config(environ=env).source_sha256 != execution.source_sha256:
            report["stop_reason"] = "policy_drift"
            break
        if live and not order_by_health((route,), environ=env):
            report["stop_reason"] = "account_cooldown"
            break
        reserved += cost
        report["reserved_cost_usd"] = str(reserved)
        report["planned_endpoints"].append(tag)
        if not live:
            continue
        timeout = min(remaining, timeout_seconds, resolve_attempt_timeout(
            route.provider, route.wire_model, environ=env, default=execution.execution.attempt_timeout_seconds))
        request = _request_for(route, tag, metadata[tag], max_tokens, timeout)
        try:
            sample = _invoke(request, tag, timeout, policy_file=execution.source)
        except KeyboardInterrupt:
            sample = result("cancelled", time.monotonic())
        if sample["outcome"] == "success" and (
                sample["cost_usd"] is None or _number(sample["cost_usd"]) > cost
                or type(sample["input_tokens"]) is not int or not 0 <= sample["input_tokens"] <= INPUT_BOUND
                or type(sample["output_tokens"]) is not int or not 0 <= sample["output_tokens"] <= max_tokens):
            sample = {**sample, "outcome": "accounting_limit"}
        request_id = uuid4().hex
        report["samples"].append({"endpoint": tag, "at": time.time(), "reservation_usd": str(cost),
                                  "attempt_id": hashlib.sha256(request_id.encode()).hexdigest()[:24], "result": sample})
        record_attempt(request_id=request_id, application="subactor-proxy", function="endpoint-calibration",
                       provider="openrouter", model=wire,
                       status="success" if sample["outcome"] == "success" else "error",
                       diagnostic_code=None if sample["outcome"] == "success" else "SUBLLM-CALIBRATION-FAILED",
                       duration_ms=round(sample["total_seconds"] * 1000), usage={
                           "prompt_tokens": sample["input_tokens"], "completion_tokens": sample["output_tokens"]})
        outcome = sample["outcome"]
        if outcome != "success":
            if outcome in {"http_401", "http_402", "http_403", "http_429", "timeout", "transport_error"}:
                record_failure("openrouter", reason=outcome, latency_seconds=sample["total_seconds"],
                               policy=execution.execution, environ=env)
            report["stop_reason"] = outcome
            break
        record_success("openrouter", latency_seconds=sample["total_seconds"], policy=execution.execution, environ=env)
    return report


def _report_samples(report):
    """Validate caller-owned observations as bounded data, never trusted provenance."""
    fields = {"schema", "profile", "model", "snapshot_sha256", "observed_at", "snapshot_observed_at",
              "input_token_bound", "output_token_cap", "budget_usd", "reserved_cost_usd", "samples",
              "live", "stop_reason", "planned_endpoints"}
    if not isinstance(report, dict) or set(report) != fields:
        _fail("invalid calibration report fields")
    samples, planned = report["samples"], report["planned_endpoints"]
    if (type(report["live"]) is not bool or not isinstance(samples, list) or len(samples) > 20
            or not isinstance(planned, list) or len(planned) > 20
            or any(not isinstance(t, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._/-]{0,127}", t) for t in planned)
            or len(set(planned)) > 8 or (report["live"] and len(planned) != len(samples))
            or (not report["live"] and samples) or not isinstance(report["model"], str)
            or not isinstance(report["stop_reason"], str) or len(report["stop_reason"]) > 64):
        _fail("invalid calibration workload or samples")

    def number(value):
        value = _number(value)
        if not math.isfinite(float(value)):
            _fail("calibration number exceeds the supported range")
        return value

    for key in ("observed_at", "snapshot_observed_at"):
        number(report[key])
    budget, reserved = number(report["budget_usd"]), number(report["reserved_cost_usd"])
    if not 0 < budget <= 1 or reserved > budget:
        _fail("invalid calibration budget accounting")
    result_fields = set(result("success", 0, clock=lambda: 0))
    outcomes = {"success", "truncated", "stream_error", "incomplete_stream", "stream_limit", "billing_unknown",
                "invalid_stream", "transport_error", "timeout", "worker_error", "invalid_worker_result",
                "cancelled", "accounting_limit"}
    total = Decimal(0)
    ids = set()
    for index, row in enumerate(samples):
        if (not isinstance(row, dict) or set(row) != {"endpoint", "at", "reservation_usd", "attempt_id", "result"}
                or row["endpoint"] != planned[index] or not isinstance(row["attempt_id"], str)
                or not re.fullmatch("[0-9a-f]{24}", row["attempt_id"]) or row["attempt_id"] in ids):
            _fail("invalid calibration attempt binding")
        ids.add(row["attempt_id"])
        number(row["at"])
        reservation = number(row["reservation_usd"])
        total += reservation
        sample = row["result"]
        if not isinstance(sample, dict) or set(sample) != result_fields or sample["schema"] != RESULT_SCHEMA:
            _fail("invalid calibration sample fields")
        outcome = sample["outcome"]
        if (not isinstance(outcome, str) or (outcome not in outcomes and not (
                re.fullmatch(r"http_[0-9]{3}", outcome) and 100 <= int(outcome[5:]) <= 599))):
            _fail("invalid calibration sample outcome")
        for key in ("ttft_seconds", "first_reasoning_seconds", "total_seconds", "tokens_per_second"):
            value = sample[key]
            if value is not None and (type(value) not in (int, float) or not math.isfinite(value) or value < 0):
                _fail("invalid calibration timing")
        if sample["total_seconds"] is None or any(
                sample[k] is not None and sample[k] > sample["total_seconds"]
                for k in ("ttft_seconds", "first_reasoning_seconds")):
            _fail("inconsistent calibration timing")
        for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
            if sample[key] is not None and (type(sample[key]) is not int or not 0 <= sample[key] <= 10**12):
                _fail("invalid calibration token counts")
        if (sample["cached_input_tokens"] is not None and sample["input_tokens"] is not None
                and sample["cached_input_tokens"] > sample["input_tokens"]):
            _fail("cached input exceeds calibration input")
        cost = None if sample["cost_usd"] is None else number(sample["cost_usd"])
        if outcome == "success" and (any(sample[k] is None for k in (
                "ttft_seconds", "input_tokens", "output_tokens")) or cost is None or cost > reservation
                or sample["input_tokens"] > INPUT_BOUND or sample["output_tokens"] > report["output_token_cap"]):
            _fail("successful calibration requires bounded timing and accounting")
    if report["live"] and total != reserved:
        _fail("calibration reservations do not match attempts")
    return samples


def rank_calibrated(snapshot, report, *, now=None, quantile="p50", latency_penalty_usd_per_second="0"):
    """Rank the fixed probe workload, not arbitrary task sizes or production SLOs."""
    now = time.time() if now is None else now
    if not isinstance(report, dict):
        _fail("calibration report must be an object")
    if (report.get("schema") != SCHEMA or report.get("profile") != PROFILE
            or report.get("snapshot_sha256") != _digest(snapshot) or report.get("input_token_bound") != INPUT_BOUND
            or type(report.get("output_token_cap")) is not int or not 1 <= report["output_token_cap"] <= 256
            or quantile not in {"p50", "p90"} or not isinstance(report.get("samples"), list)
            or len(report["samples"]) > 20):
        _fail("calibration profile, snapshot or sample binding is invalid")
    samples = _report_samples(report)
    age = _number(now) - _number(report["observed_at"])
    if not 0 <= age <= 900:
        _fail("calibration observation is stale or from the future")
    penalty = _number(latency_penalty_usd_per_second)
    quotes = rank_endpoints(snapshot, model=report["model"], observed_at=report["snapshot_observed_at"], now=now,
                            input_tokens=INPUT_BOUND, output_tokens=report["output_token_cap"])
    if any(row["endpoint"] not in {q["tag"] for q in quotes} for row in samples):
        _fail("calibration attempt is outside the eligible snapshot workload")
    failed = {row["endpoint"] for row in samples
              if row["result"]["outcome"] != "success" and 0 <= _number(now) - _number(row["at"]) <= 900}
    quotes = [q for q in quotes if q["tag"] not in failed]
    for quote in quotes:
        values = []
        for row in report["samples"]:
            sample = row["result"]
            if row["endpoint"] != quote["tag"] or sample["outcome"] != "success":
                continue
            if not 0 <= _number(now) - _number(row["at"]) <= 900:
                continue
            if sample["ttft_seconds"] is not None:
                value = float(_number(sample["ttft_seconds"]))
                if not math.isfinite(value):
                    _fail("calibration timing exceeds the supported range")
                values.append(value)
        minimum = 3 if quantile == "p50" else 20
        measured = len(values) >= minimum
        latency = (statistics.median(values) if quantile == "p50" else sorted(values)[math.ceil(.9 * len(values)) - 1]
                   ) if measured else None
        quote.update(local_ttft_seconds=latency, local_samples=len(values), local_quantile=quantile,
                     unmeasured=not measured, profile=PROFILE,
                     score=str(Decimal(quote["estimated_cost_usd"]) + penalty * Decimal(str(latency or 0))))
    return sorted(quotes, key=lambda q: (q["unmeasured"] if penalty else False, Decimal(q["score"]), q["tag"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--observed-at", required=True, type=float)
    parser.add_argument("--model", required=True, choices=sorted(MODELS_ALLOWED))
    parser.add_argument("--endpoint", action="append", required=True)
    parser.add_argument("--max-cost-usd", required=True)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--live", action="store_true", help="explicitly permit bounded paid probes; default is dry-run")
    args = parser.parse_args(argv)
    try:
        with args.snapshot.open("rb") as stream:
            raw = stream.read(2_000_001)
        if len(raw) > 2_000_000:
            _fail("snapshot exceeds2MB")
        report = calibrate(json.loads(raw), model=args.model, observed_at=args.observed_at,
                           endpoints=args.endpoint, max_cost_usd=args.max_cost_usd, samples=args.samples,
                           max_tokens=args.max_tokens, timeout_seconds=args.timeout, live=args.live)
        print(json.dumps(report, allow_nan=False))
    except (OSError, ValueError, SubLLMError):
        print(json.dumps({"schema": SCHEMA, "stop_reason": "invalid_configuration"}))
        return 2
    return 0 if not args.live or report["stop_reason"] in {"sample_limit", "budget_limit"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
