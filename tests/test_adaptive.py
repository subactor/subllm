from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from subllm import adaptive
from subllm.client_types import CompletionResponse, _RetryableAttemptError
from subllm.errors import CompletionError
from subllm.types import ResolvedRoute


def route(provider, model, priority=1, transport="openai-compatible"):
    return ResolvedRoute(
        application="subactor-proxy",
        application_name="test",
        application_url="https://example.test",
        function="chat",
        provider=provider,
        model=model,
        priority=priority,
        api_base="http://localhost",
        api_key_env="",
        litellm_model=model,
        wire_model=model,
        extra_headers={},
        transport=transport,
        api_key="",
    )


@pytest.fixture
def config(tmp_path):
    return {
        "classes": {"strong": ["pro-a", "pro-b"], "fast": ["small"], "any": ["auto"]},
        "aliases": {"external/pro": "strong", "external/fast": "fast"},
        "state": str(tmp_path / "availability.db"),
        "ttl": 900,
        "probe_timeout": 2,
        "sweep_budget": 10,
        "sweep_interval": 60,
    }


def run(config, requested, invoke, routes, **kwargs):
    return adaptive.execute(
        config,
        requested,
        [{"role": "user", "content": "private task"}],
        build_routes=lambda m: [r for r in routes if r.model == m],
        invoke=invoke,
        timeout_seconds=30,
        **kwargs,
    )


def test_quota_probes_all_remaining_classes_and_prioritizes_success(config):
    routes = [route("a", "pro-a"), route("b", "pro-b", 2), route("c", "small"), route("d", "auto")]
    calls = []

    def invoke(r, messages, **kwargs):
        calls.append((r.model, messages[0]["content"], kwargs["timeout_seconds"]))
        if r.provider == "a":
            raise _RetryableAttemptError("quota", outcome="http_402")
        return CompletionResponse("ok", r.provider, r.wire_model)

    result = run(config, "pro-a", invoke, routes)
    assert result.provider == "b"
    assert [m for m, prompt, _ in calls if "Availability test" in prompt] == ["pro-b", "small", "auto"]
    assert [m for m, prompt, _ in calls if prompt == "private task"] == ["pro-a", "pro-b"]
    assert all(0 < limit <= 30 for _, _, limit in calls)
    calls.clear()
    assert run(config, "pro-a", invoke, routes).model == "pro-b"
    assert len(calls) == 1  # persisted across calls, no repeated exhausted provider
    assert "private task" not in Path(config["state"]).read_bytes().decode("latin1")


def test_strong_never_uses_fast_or_unknown_auto(config):
    called = []

    def invoke(r, *args, **kwargs):
        called.append(r.model)
        raise _RetryableAttemptError("missing", outcome="model_unavailable", provider_level=False)

    with pytest.raises(CompletionError, match="class-compatible"):
        run(config, "external/pro", invoke, [route("a", "pro-a"), route("c", "small"), route("d", "auto")])
    assert called == ["pro-a"]


def test_fast_prefers_its_class_before_stronger(config):
    def invoke(r, *args, **kwargs):
        return CompletionResponse("ok", r.provider, r.model)

    assert run(config, "external/fast", invoke, [route("a", "pro-a"), route("c", "small", 100)]).model == "small"
    assert run(config, "external/fast", invoke, [route("a", "pro-a")]).model == "pro-a"


def test_missing_pinned_model_uses_class_equivalent(config):
    def invoke(r, *args, **kwargs):
        return CompletionResponse("ok", r.provider, r.model)

    assert run(config, "pro-a", invoke, [route("b", "pro-b")]).model == "pro-b"


def test_expired_failure_is_retested(config):
    r = route("a", "pro-a")
    adaptive._save(config, r, "text", "http_429", 1)
    with sqlite3.connect(config["state"]) as db:
        db.execute("UPDATE availability SET observed=0")
    assert run(config, "pro-a", lambda r, *a, **k: CompletionResponse("ok", r.provider, r.model), [r]).model == "pro-a"


def test_probe_failure_does_not_promote_provider(config):
    def invoke(r, *args, **kwargs):
        if r.model == "pro-a":
            raise _RetryableAttemptError("quota", outcome="http_429")
        return CompletionResponse("not json", r.provider, r.model)

    with pytest.raises(CompletionError):
        run(
            config, "pro-a", invoke, [route("a", "pro-a"), route("b", "pro-b")], response_format={"type": "json_object"}
        )
    assert adaptive._observations(config, "json_object")[("b", "pro-b")][0] != "ok"


def test_probe_singleflight_across_connections(config):
    with ThreadPoolExecutor(max_workers=6) as pool:
        claims = list(pool.map(lambda _: adaptive._claim_sweep(config, "text"), range(6)))
    assert claims.count(True) == 1


def test_format_and_explicit_request_errors_are_not_quota(config):
    def invoke(*args, **kwargs):
        raise CompletionError("unsupported request")

    with pytest.raises(CompletionError, match="unsupported request"):
        run(config, "pro-a", invoke, [route("a", "pro-a")])
    assert adaptive._observations(config, "text") == {}


def test_cli_quota_classified_without_raw_secret(config):
    assert adaptive.failure_kind(CompletionError("redacted", diagnostic_code="SUBLLM-CLAUDE-HTTP-429")) == "http_429"
    assert (
        adaptive.failure_kind(CompletionError("redacted", diagnostic_code="SUBLLM-CODEX-TIMEOUT"))
        == "provider_unavailable"
    )


def test_schema_excludes_cursor_auto(config):
    def invoke(*a, **k):
        pytest.fail("unsupported transport invoked")

    with pytest.raises(CompletionError, match="no enabled provider"):
        run(
            config,
            "auto",
            invoke,
            [route("cursor-cli", "auto", transport="cursor-cli")],
            response_format={"type": "json_schema"},
        )


def test_policy_aliases_are_explicit(tmp_path):
    p = tmp_path / "policy.json"
    p.write_text(json.dumps({"classes": {"strong": ["model"]}, "aliases": {"vendor/required": "strong"}}))
    c = adaptive.policy({"SUBLLM_ADAPTIVE_POLICY": str(p)})
    assert adaptive.requested_class(c, "vendor/required") == "strong"
    assert adaptive.requested_class(c, "unrecognized-pro") is None
    p.write_text(json.dumps({"classes": {"strong": ["model"], "fast": ["model"]}}))
    with pytest.raises(CompletionError, match="invalid adaptive"):
        adaptive.policy({"SUBLLM_ADAPTIVE_POLICY": str(p)})


def test_proxy_pinned_model_and_service_route_use_shared_policy(config, tmp_path, monkeypatch):
    import subllm.client_routes as clients
    import subllm.proxy as proxy

    p = tmp_path / "policy.json"
    config["routes"] = {"subactor-proxy/chat": "strong"}
    p.write_text(json.dumps(config))
    monkeypatch.setenv("SUBLLM_ADAPTIVE_POLICY", str(p))
    monkeypatch.setenv("SUBLLM_ADAPTIVE_STATE", config["state"])
    monkeypatch.setattr(
        proxy, "_build_model_resolved_routes", lambda m, *a, **k: [route("b", "pro-b")] if m == "pro-b" else []
    )

    def invoke(r, *a, **k):
        return CompletionResponse("ok", r.provider, r.model)

    monkeypatch.setattr(proxy, "_complete_route", invoke)
    monkeypatch.setattr(clients, "_complete_route", invoke)
    assert proxy._complete_model_direct("external/pro", [{"content": "hello"}]).model == "pro-b"
    assert clients.complete("subactor-proxy", "chat", [{"content": "hello"}]).model == "pro-b"


def test_runner_recognizes_nonzero_quota_envelope(tmp_path):
    import sys

    from subllm.cli_common import run_cli

    script = (
        'import json,sys;print(json.dumps({"is_error":True,"api_error_status":429,"result":"private"}));sys.exit(1)'
    )
    with pytest.raises(CompletionError) as err:
        run_cli(
            [sys.executable, "-c", script],
            stdin_bytes=None,
            timeout_seconds=2,
            root=tmp_path,
            code_prefix="SUBLLM-TEST",
            label="Test",
        )
    assert err.value.diagnostic_code == "SUBLLM-TEST-HTTP-429"
    assert "private" not in str(err.value)


def test_successful_answer_mentioning_limits_is_not_quota():
    from subllm.cli_common import quota_failure

    assert not quota_failure(b'{"type":"result","is_error":false,"result":"quota exceeded"}')
    assert quota_failure(b'{"type":"error","message":"usage_limit_reached"}')
    assert quota_failure(b'{"type":"result","is_error":true,"api_error_status":429}')


def test_measured_latency_updates_alternative_priority(config):
    a, b = route("a", "pro-a", 1), route("b", "pro-b", 99)
    adaptive._save(config, a, "text", "ok", 80)
    adaptive._save(config, b, "text", "ok", 6)
    result = run(config, "external/pro", lambda r, *a, **k: CompletionResponse("ok", r.provider, r.model), [a, b])
    assert result.provider == "b"
