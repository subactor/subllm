"""Real-request failover reuses shared health without speculative API probes."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest
from test_adaptive import config as config
from test_adaptive import route, run

from subllm import adaptive
from subllm.client_types import CompletionResponse, _RetryableAttemptError
from subllm.errors import PROVIDER_CHAIN_EXHAUSTED_CODE, CompletionError
from subllm.health import record_failure
from subllm.policy_config import load_policy_config


def block(provider, *, now=None):
    record_failure(provider, reason="http_402", latency_seconds=0.01,
                   policy=load_policy_config().execution, now=now)


def test_failure_uses_next_real_request_without_any_probe(config):
    calls = []

    def invoke(r, messages, **kwargs):
        calls.append((r.provider, messages[0]["content"]))
        if r.provider == "a":
            raise _RetryableAttemptError("payment required", outcome="http_402")
        return CompletionResponse("ok", r.provider, r.model)

    result = run(config, "external/pro", invoke,
                 [route("a", "pro-a", 1), route("b", "pro-b", 2), route("c", "small")])
    assert result.provider == "b"
    assert calls == [("a", "private task"), ("b", "private task")]


def test_declared_priority_precedes_cached_success_and_latency(config):
    adaptive._save(config, route("b", "pro-b", 99), "text", "ok", 0.001)
    result = run(config, "external/pro", lambda r, *a, **kw: CompletionResponse("ok", r.provider, r.model),
                 [route("a", "pro-a", 1), route("b", "pro-b", 99)])
    assert result.provider == "a"


def test_payment_failure_skips_other_models_on_the_same_account(config):
    config["classes"]["strong"].append("pro-c")
    calls = []

    def invoke(r, *a, **kw):
        calls.append((r.provider, r.model))
        if r.provider == "a":
            raise _RetryableAttemptError("payment required", outcome="http_402")
        return CompletionResponse("ok", r.provider, r.model)

    result = run(config, "external/pro", invoke,
                 [route("a", "pro-a", 1), route("a", "pro-b", 2), route("b", "pro-c", 3)])
    assert result.provider == "b"
    assert calls == [("a", "pro-a"), ("b", "pro-c")]


def test_adaptive_route_honors_shared_account_cooldown(config):
    block("a")
    result = run(config, "external/pro", lambda r, *a, **kw: CompletionResponse("ok", r.provider, r.model),
                 [route("a", "pro-a", 1), route("b", "pro-b", 2)])
    assert result.provider == "b"


def test_account_cooldown_outlives_model_observation_cache(config):
    calls = []

    def invoke(r, *a, **kw):
        calls.append(r.provider)
        if r.provider == "a":
            raise _RetryableAttemptError("payment required", outcome="http_402")
        return CompletionResponse("ok", r.provider, r.model)

    routes = [route("a", "pro-a", 1), route("b", "pro-b", 2)]
    assert run(config, "external/pro", invoke, routes).provider == "b"
    with sqlite3.connect(config["state"]) as db:
        db.execute("UPDATE availability SET observed=0")
    calls.clear()
    assert run(config, "external/pro", invoke, routes).provider == "b"
    assert calls == ["b"]


def test_expired_account_cooldown_restores_priority(config):
    policy = load_policy_config().execution
    block("a", now=time.time() - policy.uncredited_cooldown_seconds - 1)
    adaptive._save(config, route("b", "pro-b", 99), "text", "ok", 0.001)
    result = run(config, "external/pro", lambda r, *a, **kw: CompletionResponse("ok", r.provider, r.model),
                 [route("a", "pro-a", 1), route("b", "pro-b", 99)])
    assert result.provider == "a"


def test_all_accounts_cooling_returns_one_chain_error_without_transport(config):
    block("a")
    block("b")
    with pytest.raises(CompletionError, match="no available class-compatible") as exc:
        run(config, "external/pro", lambda *a, **kw: pytest.fail("blocked API contacted"),
            [route("a", "pro-a"), route("b", "pro-b")])
    assert exc.value.diagnostic_code == PROVIDER_CHAIN_EXHAUSTED_CODE


def test_legacy_payment_error_keeps_its_billing_classification():
    assert adaptive.failure_kind(CompletionError("redacted", diagnostic_code="SUBLLM-CLAUDE-HTTP-402")) == "http_402"


def test_model_scoped_failure_keeps_other_model_on_same_provider(config):
    calls = []

    def invoke(r, *a, **kw):
        calls.append(r.model)
        if r.model == "pro-a":
            raise _RetryableAttemptError("missing", outcome="model_unavailable", provider_level=False)
        return CompletionResponse("ok", r.provider, r.model)

    assert run(config, "external/pro", invoke, [route("a", "pro-a", 1), route("a", "pro-b", 2)]).model == "pro-b"
    assert calls == ["pro-a", "pro-b"]


def test_fresh_process_reuses_account_failure(config):
    block("a")
    root = Path(__file__).resolve().parents[1]
    code = """
import json, sys
from test_adaptive import route, run
from subllm.client_types import CompletionResponse
c=json.loads(sys.argv[1])
r=run(c,'external/pro',lambda r,*a,**kw: CompletionResponse('ok',r.provider,r.model),
      [route('a','pro-a',1),route('b','pro-b',2)])
print(r.provider)
"""
    env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(root / "src"), str(root / "tests")]))
    child = subprocess.run([sys.executable, "-B", "-c", code, json.dumps(config)],
                           capture_output=True, text=True, env=env, cwd=root, timeout=30)
    assert child.returncode == 0, child.stderr
    assert child.stdout.strip() == "b"
