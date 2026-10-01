"""Quota recovery for configured model classes, shared by API and route consumers.

SUBLLM_ADAPTIVE_POLICY points to operator-owned JSON, for example::

    {"classes": {"fast": ["gpt-5.6-luna"],
                 "strong": ["gemini-3.1-pro-high"], "any": ["cursor-auto"]},
     "aliases": {"external-pro": "strong"},
     "routes": {"validator-agent/direct-pr-review": "strong"}}

Classes are operator requirements, not measured benchmark equivalence. A lower
class never satisfies a higher one; unknown/Auto models only satisfy ``any``.
Only declared models with enabled, credential-ready transports are probed.
Small synthetic probes do not receive user content. Availability is stored per
provider/model/format in SQLite; successful probes are not approval evidence.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

from .client_types import CompletionAttempt, _RetryableAttemptError
from .errors import CompletionError

LEVELS = {"any": 0, "fast": 1, "balanced": 2, "strong": 3}


def policy(environ=None):
    env = os.environ if environ is None else environ
    path = env.get("SUBLLM_ADAPTIVE_POLICY")
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text())
        classes = data["classes"]
        if not isinstance(classes, dict) or not classes:
            raise ValueError()
        seen = set()
        for tier, models in classes.items():
            if tier not in LEVELS or not isinstance(models, list):
                raise ValueError()
            for model in models:
                if not isinstance(model, str) or not model or model in seen:
                    raise ValueError()
                seen.add(model)
        for name in ("aliases", "routes"):
            if not isinstance(data.get(name, {}), dict):
                raise ValueError()
            if any(not isinstance(k, str) or v not in LEVELS for k, v in data.get(name, {}).items()):
                raise ValueError()
        for key, default in (("probe_timeout", 60), ("sweep_budget", 180), ("ttl", 900), ("sweep_interval", 300)):
            value = data.setdefault(key, default)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError()
        data["state"] = env.get("SUBLLM_ADAPTIVE_STATE", str(Path(path).with_suffix(".sqlite3")))
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise CompletionError("invalid adaptive routing policy", diagnostic_code="SUBLLM-ADAPTIVE-POLICY") from exc


def requested_class(config, model):
    if model in config.get("aliases", {}):
        return config["aliases"][model]
    return next((tier for tier, models in config["classes"].items() if model in models), None)


def failure_kind(exc):
    if isinstance(exc, _RetryableAttemptError):
        return exc.outcome
    code = getattr(exc, "diagnostic_code", "") or ""
    if code.endswith(("HTTP-429", "HTTP-402", "QUOTA")):
        return "http_429"
    if code.endswith(("TIMEOUT", "FAILED", "UNAVAILABLE")):
        return "provider_unavailable"
    return None


@contextmanager
def _connect(config):
    path = Path(config["state"]).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Create privately before sqlite opens it. No prompts or credentials stored.
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    os.close(fd)
    db = sqlite3.connect(path, timeout=2)
    db.execute(
        "CREATE TABLE IF NOT EXISTS availability (provider TEXT, model TEXT, format TEXT, status TEXT, "
        "observed REAL, latency REAL, PRIMARY KEY(provider,model,format))"
    )
    db.execute("CREATE TABLE IF NOT EXISTS sweeps (format TEXT PRIMARY KEY, started REAL)")
    try:
        with db:
            yield db
    finally:
        db.close()


def _key(route, fmt):
    return route.provider, route.model, fmt


def _save(config, route, fmt, status, duration):
    try:
        with _connect(config) as db:
            db.execute(
                "INSERT OR REPLACE INTO availability VALUES (?,?,?,?,?,?)",
                (*_key(route, fmt), status, time.time(), duration),
            )
    except (OSError, sqlite3.Error):
        pass  # Health observations must not prevent an otherwise valid request.


def _observations(config, fmt):
    try:
        with _connect(config) as db:
            return {
                (p, m): (s, latency)
                for p, m, s, latency in db.execute(
                    "SELECT provider,model,status,latency FROM availability WHERE format=? AND observed>?",
                    (fmt, time.time() - config["ttl"]),
                )
            }
    except (OSError, sqlite3.Error):
        return {}


def _claim_sweep(config, fmt):
    try:
        with _connect(config) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT started FROM sweeps WHERE format=?", (fmt,)).fetchone()
            if row and time.time() - row[0] < max(config["sweep_interval"], config["sweep_budget"]):
                return False
            db.execute("INSERT OR REPLACE INTO sweeps VALUES (?,?)", (fmt, time.time()))
            return True
    except (OSError, sqlite3.Error):
        return False  # Cannot coordinate a sweep: ordinary bounded failover still works.


def _compatible(route, messages, fmt):
    if fmt == "json_schema" and route.transport == "cursor-cli":
        return False
    nontext = any(
        isinstance(m.get("content"), list) and any(p.get("type") != "text" for p in m["content"]) for m in messages
    )
    if nontext:
        from .policy import MODELS

        spec = MODELS.get(route.model)
        return bool(spec and spec.vision and route.transport == "openai-compatible")
    return True


def _check_response(response, fmt):
    if not response.content.strip():
        raise _RetryableAttemptError("empty provider response", outcome="invalid_response", provider_level=False)
    if fmt in {"json_object", "json_schema"}:
        try:
            value = json.loads(response.content)
        except ValueError as exc:
            raise _RetryableAttemptError(
                "provider returned invalid JSON", outcome="invalid_response", provider_level=False
            ) from exc
        if fmt == "json_object" and not isinstance(value, dict):
            raise _RetryableAttemptError(
                "provider returned a non-object JSON response", outcome="invalid_response", provider_level=False
            )


def execute(
    config,
    requested,
    messages,
    *,
    build_routes,
    invoke,
    timeout_seconds,
    response_format=None,
    request_id=None,
    cwd=None,
    environ=None,
):
    """Probe all configured remaining candidates on quota, then retry by class.

    Each call retains its wall-clock budget. A sweep consumes at most half the
    remaining budget, divided between every remaining candidate. Truncated
    sweeps are observations, never assertions that untested candidates work.
    """
    tier = requested_class(config, requested)
    if tier is None:
        raise CompletionError("requested model has no declared replacement class")
    fmt = (response_format or {}).get("type", "text")
    if not messages or not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise CompletionError("messages and a positive finite timeout are required")
    from .policy_config import load_policy_config

    execution = load_policy_config(environ=environ).execution
    deadline = time.monotonic() + timeout_seconds
    catalog = {m: LEVELS[t] for t, models in config["classes"].items() for m in models}
    pool = []
    for model in catalog:
        pool.extend(r for r in build_routes(model) if _compatible(r, messages, fmt))
    # A builder can expose the same provider/model from several aliases.
    pool = list({(r.provider, r.model): r for r in pool}.values())
    eligible = [r for r in pool if catalog[r.model] >= LEVELS[tier]]
    if not eligible:
        raise CompletionError(
            "no enabled provider meets the requested model class", diagnostic_code="SUBLLM-NO-EQUIVALENT-MODEL"
        )
    attempts = []
    attempted = set()
    swept = False
    while len(attempts) < (execution.max_attempts if execution.failover_enabled else 1):
        observed = _observations(config, fmt)
        candidates = [
            r
            for r in eligible
            if (r.provider, r.model) not in attempted and observed.get((r.provider, r.model), ("ok", 0))[0] == "ok"
        ]

        def rank(r, observed=observed):
            status = observed.get((r.provider, r.model))
            return (
                catalog[r.model] - LEVELS[tier] if tier != "any" else 0,
                0 if status else 1,
                0 if r.model == requested else 1,
                status[1] if status else float("inf"),
                r.priority,
            )

        candidates.sort(key=rank)
        remaining = deadline - time.monotonic()
        if not candidates or remaining <= 0:
            break
        route = candidates[0]
        attempted.add((route.provider, route.model))
        started = time.monotonic()
        try:
            from .policy_config import resolve_attempt_timeout

            budget = resolve_attempt_timeout(
                route.provider, route.wire_model, default=execution.attempt_timeout_seconds, environ=environ
            )
            response = invoke(
                route,
                messages,
                timeout_seconds=min(remaining, budget),
                response_format=response_format,
                request_id=request_id,
                cwd=cwd or Path.cwd(),
            )
            _check_response(response, fmt)
        except CompletionError as exc:
            kind = failure_kind(exc)
            if kind is None:
                raise
            duration = time.monotonic() - started
            _save(config, route, fmt, kind, duration)
            attempts.append(CompletionAttempt(route.provider, route.wire_model, kind, round(duration * 1000)))
            if execution.failover_enabled and kind in {"http_402", "http_429"} and not swept:
                swept = True
                if _claim_sweep(config, fmt):
                    _sweep(config, pool, attempted, fmt, response_format, invoke, deadline, cwd)
            continue
        duration = time.monotonic() - started
        _save(config, route, fmt, "ok", duration)
        attempts.append(CompletionAttempt(route.provider, route.wire_model, "success", round(duration * 1000)))
        return replace(response, attempts=tuple(attempts))
    raise CompletionError(
        "no available class-compatible model within the request budget", diagnostic_code="SUBLLM-NO-EQUIVALENT-MODEL"
    )


def _sweep(config, pool, attempted, fmt, response_format, invoke, deadline, cwd):
    candidates = [r for r in pool if (r.provider, r.model) not in attempted]
    stop = time.monotonic() + min(config["sweep_budget"], max(0, deadline - time.monotonic()) / 2)
    prompt = [
        {
            "role": "user",
            "content": (
                "Availability test. Return a minimal valid response matching the requested format. "
                'For JSON object return {"ok":true}.'
            ),
        }
    ]
    for index, route in enumerate(candidates):
        remaining = stop - time.monotonic()
        if remaining <= 0:
            break
        start = time.monotonic()
        try:
            result = invoke(
                route,
                prompt,
                timeout_seconds=min(config["probe_timeout"], remaining / (len(candidates) - index)),
                response_format=response_format,
                request_id=None,
                cwd=cwd or Path.cwd(),
            )
            _check_response(result, fmt)
            status = "ok"
        except Exception as exc:
            status = failure_kind(exc) or "probe_failed"
        _save(config, route, fmt, status, time.monotonic() - start)
