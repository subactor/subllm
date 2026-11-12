"""Exact completion reuse with real native storage and synthetic provider effects."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from uuid import uuid4

import pytest
from procache import SQLiteResponseCache
from test_completion_audit import captured as captured
from test_http_transport_bounds import serve

from subllm import (
    CompletionCache,
    CompletionError,
    CompletionResponse,
    GenerationBudget,
    client_routes,
    complete,
    usage,
)
from subllm import completion_cache as module


@pytest.fixture
def config(tmp_path):
    return CompletionCache(tmp_path / "private" / "completions.sqlite3", ttl=60,
                           scope="test-account", model_revision="test-revision", criterion_version="test-v1")


def call(config, **kwargs):
    return complete("onedev-agent", "code-edit", [{"role": "user", "content": "test-private-prompt"}],
                    cache=config, request_id=kwargs.pop("request_id", uuid4().hex), **kwargs)


def count_attempts():
    with closing(sqlite3.connect(usage.journal_path())) as db:
        return db.execute("SELECT COUNT(*) FROM attempts").fetchone()[0]


def test_miss_hit_has_one_billed_attempt_two_native_receipts_and_immutable_source_usage(captured, config):
    first, second = call(config), call(config)
    assert first.cache.state == "miss" and second.cache.state == "hit"
    assert captured.calls == [first.model] and count_attempts() == 1
    assert first.audit.request_id != second.audit.request_id
    assert second.attempts == () and second.audit.attempts[0].status == "cache_hit"
    assert second.audit.attempts[0].journal is None and second.audit.attempts[0].journal_state == "disabled"
    assert second.audit.state == "stored" and set(second.usage.values()) == {0}
    assert second.cache.source_request_id == first.audit.request_id
    assert second.cache.source_archive == first.audit.attempts[0].archive
    assert dict(second.cache.source_usage) == {"prompt_tokens": 3, "completion_tokens": 2}
    assert second.cache.content_digest == hashlib.sha256(first.content.encode()).hexdigest()
    native = second.audit.attempts[0].archive
    assert native != first.audit.attempts[0].archive
    record = captured.store.get_interaction(native.id, native.day)
    assert record["kind"] == "completion_replay" and record["correlation_id"] == second.audit.request_id
    assert record["response"]["usage"]["output_tokens"] == 0
    assert record["response"]["raw"]["cache"]["source_usage"]["completion_tokens"] == 2
    assert record["request"]["cache"]["source_request_id"] == first.audit.request_id
    assert config.path.stat().st_mode & 0o777 == 0o600
    for private in (b"test-private-prompt", b"test.audit-fixture"):
        assert private not in config.path.read_bytes()
    encoded = json.dumps(asdict(second.cache))
    for private in ("test-private-prompt", first.content, "test.audit-fixture", str(config.path)):
        assert private not in encoded
    with pytest.raises(FrozenInstanceError):
        second.cache.state = "miss"


def test_hit_does_not_consume_shared_generation_budget(captured, config):
    budget = GenerationBudget(10)
    first = call(config, generation_budget=budget)
    second = call(config, generation_budget=budget)
    assert first.generation.output_tokens == 2 and budget.output_tokens == 2
    assert second.cache.state == "hit" and second.generation.output_tokens == 0
    assert second.generation.attempts == 0 and second.generation.remaining_campaign_tokens == 8


@pytest.mark.parametrize("field", ["scope", "model_revision", "criterion_version"])
def test_operator_identity_changes_are_misses(captured, config, field):
    call(config)
    second = call(replace(config, **{field: "test-other"}))
    assert second.cache.state == "miss" and len(captured.calls) == 2


@pytest.mark.parametrize("field,value", [
    ("api_key", "test.other-account"), ("wire_model", "test-other-model"),
    ("api_base", "https://test.invalid/v2"), ("model_parameters", {"temperature": "0.3"}),
    ("extra_headers", {"X-Account": "test-other-account"}), ("policy_sha256", "test-other-policy"),
])
def test_resolved_request_and_credential_changes_are_misses(captured, config, monkeypatch, field, value):
    call(config)
    route = replace(captured.route, **{field: value})
    monkeypatch.setattr(client_routes, "available_routes", lambda *a, **kw: [route])
    assert call(config).cache.state == "miss" and len(captured.calls) == 2


def test_policy_file_generation_and_response_format_changes_are_misses(captured, config, monkeypatch, tmp_path):
    call(config)
    assert call(config, generation_limits={"max_output_tokens": 8}).cache.state == "miss"
    assert call(config, response_format={"type": "text"}).cache.state == "miss"
    path = tmp_path / "policy.toml"
    path.write_text(Path(os.environ["SUBLLM_POLICY_FILE"]).read_text() + "\n# test-policy-revision\n")
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(path))
    assert call(config).cache.state == "miss" and len(captured.calls) == 4


def test_message_order_is_significant_but_object_key_order_is_not(captured, config):
    messages = [{"role": "system", "content": "test-system"}, {"role": "user", "content": "test-user"}]
    first = complete("onedev-agent", "code-edit", messages, cache=config)
    reordered = [{"content": item["content"], "role": item["role"]} for item in messages]
    assert complete("onedev-agent", "code-edit", reordered, cache=config).cache.state == "hit"
    assert complete("onedev-agent", "code-edit", list(reversed(messages)), cache=config).cache.state == "miss"
    assert len(captured.calls) == 2 and first.cache.state == "miss"


def test_quality_predicate_runs_on_hit_and_rejected_candidate_is_regenerated(captured, config, monkeypatch):
    call(config)
    observed = []

    def accept(response):
        observed.append(response.content)
        return response.content == "test-new-response"

    def invoke(route, messages, **kwargs):
        captured.calls.append(route.wire_model)
        return CompletionResponse("test-new-response", route.provider, route.wire_model, {"output_tokens": 1}, "stop")

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    assert call(config, quality_gate=accept).content == "test-new-response"
    assert observed == ["test-private-response", "test-new-response"] and len(captured.calls) == 2


def test_broken_validator_never_causes_a_new_inference(captured, config):
    call(config)

    def broken(response):
        raise RuntimeError("test-private-error")

    with pytest.raises(CompletionError, match="validator failed"):
        call(config, quality_gate=broken)
    assert len(captured.calls) == 1


def test_replay_validator_observes_zero_new_usage_and_source_attribution(captured, config):
    call(config)
    seen = []

    def accept(response):
        seen.append(response.cache.state)
        return (response.cache.state == "hit" and response.usage["output_tokens"] == 0
                and dict(response.cache.source_usage)["completion_tokens"] == 2)

    assert call(config, quality_gate=accept).cache.state == "hit"
    assert seen == ["hit"] and len(captured.calls) == 1


def test_quality_schema_change_is_bound_and_validated(captured, config, monkeypatch):
    def invoke(route, messages, **kwargs):
        captured.calls.append(route.wire_model)
        return CompletionResponse('{"ok":true}', route.provider, route.wire_model, {}, "stop")

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    call(config, quality_schema=True)
    assert call(config, quality_schema={"type": "object"}).cache.state == "miss"
    assert len(captured.calls) == 2


def test_force_generation_bypasses_cached_answer(captured, config):
    call(config)
    assert call(config, force_generation=True).cache.state == "bypass"
    assert call(config).cache.state == "hit" and len(captured.calls) == 2


@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf"), True, "60"])
def test_invalid_ttl_rejected_before_effect(tmp_path, value):
    with pytest.raises(CompletionError):
        CompletionCache(tmp_path / "cache", ttl=value, scope="test", model_revision="v1", criterion_version="v1")


@pytest.mark.parametrize("phase", ["put", "_release_flight", "close"])
def test_cache_write_or_close_failure_after_success_never_repeats_inference(captured, config, monkeypatch, phase):
    def broken(*a, **kw):
        raise OSError("test-private-storage-failure")

    # close() is additive in newer procache; the immutable dev pin predates it.
    monkeypatch.setattr(SQLiteResponseCache, phase, broken, raising=phase != "close")
    response = call(config)
    assert response.content == "test-private-response" and response.audit.state == "stored"
    assert len(captured.calls) == 1 and count_attempts() == 1
    assert response.cache.state == ("miss" if phase == "close" else "unavailable")


def test_cache_unavailable_before_loading_runs_native_path_once(captured, config, monkeypatch):
    def broken(*a, **kw):
        raise OSError("test-private-storage-failure")

    monkeypatch.setattr(module, "_open_cache", broken)
    response = call(config)
    assert response.cache.state == "unavailable" and len(captured.calls) == 1


def test_original_inference_error_survives_cache_release_failure(captured, config, monkeypatch):
    def invoke(*a, **kw):
        captured.calls.append("failed")
        raise CompletionError("test-original-provider-error")

    def broken(*a, **kw):
        raise OSError("test-release-error")

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    monkeypatch.setattr(SQLiteResponseCache, "_release_flight", broken)
    with pytest.raises(CompletionError, match="test-original-provider-error"):
        call(config)
    assert captured.calls == ["failed"]


@pytest.mark.parametrize("fault", ["invalid-json", "digest", "wrong-key", "wrong-source"])
def test_corrupt_entry_is_a_miss(captured, config, fault):
    first = call(config)
    with closing(sqlite3.connect(config.path)) as db:
        value, = db.execute("SELECT value FROM responses").fetchone()
        payload = json.loads(value)
        if fault == "digest":
            payload["content"] = "test-corrupted-content"
        elif fault == "wrong-key":
            payload["key"] = "test-wrong-key"
        elif fault == "wrong-source":
            payload["archive"]["id"] = "0" * 32
        value = b"test-invalid-json" if fault == "invalid-json" else json.dumps(payload).encode()
        db.execute("UPDATE responses SET value=?", (value,))
        db.commit()
    second = call(config)
    assert second.cache.state == "miss" and len(captured.calls) == 2
    assert first.audit.request_id != second.audit.request_id


def test_missing_native_source_is_a_miss(captured, config, monkeypatch):
    call(config)
    monkeypatch.setattr(captured.store, "get_interaction", lambda *a: None)
    assert call(config).cache.state == "miss" and len(captured.calls) == 2


def test_shortening_ttl_on_restart_does_not_reuse_old_answer(captured, config, monkeypatch):
    call(config)
    stamp = time.time()
    monkeypatch.setattr(module.time, "time", lambda: stamp + 5)
    assert call(replace(config, ttl=2)).cache.state == "miss"
    assert len(captured.calls) == 2


def test_expired_entry_is_refreshed_by_one_new_inference(captured, config, monkeypatch):
    first = call(config)
    stamp = time.time()
    monkeypatch.setattr(module.time, "time", lambda: stamp + config.ttl + 1)
    second = call(config)
    assert second.cache.state == "miss" and len(captured.calls) == 2
    assert first.cache.source_request_id != second.cache.source_request_id
    assert call(config).cache.state == "hit" and len(captured.calls) == 2


def test_unknown_historical_usage_stays_separate_from_zero_new_usage(captured, config, monkeypatch):
    def invoke(route, messages, **kwargs):
        return replace(captured.invoke(route, messages, **kwargs), usage={"output_tokens": None})

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    first, second = call(config), call(config)
    assert first.usage["output_tokens"] is None and second.usage["output_tokens"] == 0
    assert dict(second.cache.source_usage) == {"output_tokens": None} and len(captured.calls) == 1


def test_incomplete_response_is_billed_but_never_cached(captured, config, monkeypatch):
    def invoke(route, messages, **kwargs):
        return replace(captured.invoke(route, messages, **kwargs), finish_reason="length")

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    for _ in range(2):
        with pytest.raises(CompletionError):
            call(config)
    assert len(captured.calls) == count_attempts() == 2
    with closing(sqlite3.connect(config.path)) as db:
        assert db.execute("SELECT COUNT(*) FROM responses").fetchone()[0] == 0


def test_parallel_misses_coalesce_and_each_operation_gets_a_receipt(captured, config, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def invoke(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return captured.invoke(*args, **kwargs)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(call, config)
        assert started.wait(2)
        second = pool.submit(call, config)
        time.sleep(0.05)
        release.set()
        responses = [first.result(5), second.result(5)]
    assert sorted(response.cache.state for response in responses) == ["hit", "miss"]
    assert len(captured.calls) == count_attempts() == 1
    assert len({response.audit.attempts[0].archive.id for response in responses}) == 2


def test_caller_mutation_cannot_change_the_body_after_its_key_is_bound(captured, config, monkeypatch):
    started, release = threading.Event(), threading.Event()
    messages = [{"role": "user", "content": "test-original-input"}]
    parameters = {"temperature": "0.2"}
    route = replace(captured.route, model_parameters=parameters)
    monkeypatch.setattr(client_routes, "available_routes", lambda *a, **kw: [route])

    def invoke(route, observed, **kwargs):
        started.set()
        assert release.wait(3)
        assert observed[0]["content"] == "test-original-input"
        assert route.model_parameters["temperature"] == "0.2"
        return captured.invoke(route, observed, **kwargs)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    with ThreadPoolExecutor(1) as pool:
        future = pool.submit(complete, "onedev-agent", "code-edit", messages, cache=config)
        assert started.wait(2)
        messages[0]["content"] = "test-mutated-input"
        parameters["temperature"] = "0.9"
        release.set()
        assert future.result(5).cache.state == "miss"
    parameters["temperature"] = "0.2"
    original = [{"role": "user", "content": "test-original-input"}]
    assert complete("onedev-agent", "code-edit", original, cache=config).cache.state == "hit"
    assert len(captured.calls) == 1


def test_cancelled_owner_releases_flight_and_waiter_can_complete(captured, config, monkeypatch):
    started, release = threading.Event(), threading.Event()
    calls = []

    def invoke(*args, **kwargs):
        calls.append("invoke")
        if len(calls) == 1:
            started.set()
            assert release.wait(3)
            raise KeyboardInterrupt()
        return captured.invoke(*args, **kwargs)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(call, config)
        assert started.wait(2)
        second = pool.submit(call, config)
        release.set()
        with pytest.raises(KeyboardInterrupt):
            first.result(5)
        assert second.result(5).cache.state == "miss"
    assert len(calls) == 2 and call(config).cache.state == "hit"


def test_wait_timeout_does_not_start_an_overlapping_inference(captured, config, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def invoke(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return captured.invoke(*args, **kwargs)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    with ThreadPoolExecutor(2) as pool:
        first = pool.submit(call, config)
        assert started.wait(2)
        try:
            with pytest.raises(CompletionError, match="cache wait timed out"):
                call(config, timeout_seconds=0.05)
        finally:
            release.set()
        assert first.result(5).cache.state == "miss"
    assert len(captured.calls) == 1


def test_same_explicit_operation_id_cannot_be_replayed(captured, config):
    call(config, request_id="test-same-id")
    with pytest.raises(CompletionError, match="new cache operation"):
        call(config, request_id="test-same-id")
    assert len(captured.calls) == 1


@pytest.mark.parametrize("transport", ["codex-cli", "cursor-sdk"])
def test_effectful_transports_are_never_cached(captured, config, monkeypatch, transport):
    route = replace(captured.route, transport=transport)
    monkeypatch.setattr(client_routes, "available_routes", lambda *a, **kw: [route])
    assert call(config).cache.state == call(config).cache.state == "bypass"
    assert len(captured.calls) == 2


def test_tool_messages_and_tool_response_payloads_are_never_cached(captured, config, monkeypatch):
    messages = [{"role": "tool", "content": "test-tool-result", "tool_call_id": "test-call"}]
    for _ in range(2):
        assert complete("onedev-agent", "code-edit", messages, cache=config).cache.state == "bypass"

    def invoke(route, messages, **kwargs):
        return replace(captured.invoke(route, messages, **kwargs), raw={"tool_calls": [{"id": "test-tool"}]})

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    assert call(config).cache.state == call(config).cache.state == "bypass"
    assert len(captured.calls) == 4


def test_native_archive_unavailable_never_creates_a_reusable_entry(captured, config, monkeypatch):
    def broken(*a, **kw):
        raise OSError("test-archive-unavailable")

    monkeypatch.setattr(captured.store, "finish", broken)
    assert call(config).cache.state == call(config).cache.state == "bypass"
    assert len(captured.calls) == count_attempts() == 2


def test_replay_archive_failure_preserves_free_answer_without_inference(captured, config, monkeypatch):
    call(config)

    def broken(*a, **kw):
        raise OSError("test-archive-unavailable")

    monkeypatch.setattr(captured.store, "finish", broken)
    response = call(config)
    assert response.cache.state == "hit" and response.audit.state == "unavailable"
    assert response.audit.attempts[0].archive is None and len(captured.calls) == count_attempts() == 1


def test_real_http_cache_persists_across_sdk_process_restart_and_coalesces(tmp_path, monkeypatch):
    payload = json.dumps({"choices": [{"message": {"content": "test-http-response"}, "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": 3, "completion_tokens": 2}}).encode()
    root = Path(__file__).resolve().parents[1]
    policy_file = tmp_path / "policy.toml"
    monkeypatch.setenv("SUBLLM_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy_file))
    monkeypatch.setenv("PYTHONPATH", str(root / "src"))
    code = '''
import json, sys
from subllm import CompletionCache, complete
cache = CompletionCache(sys.argv[1], ttl=60, scope="test-account", model_revision="v1", criterion_version="v1")
response = complete("onedev-agent", "code-edit", [{"role":"user", "content":"test-http-prompt"}],
                    cache=cache, timeout_seconds=15)
print(json.dumps({"state": response.cache.state, "request_id": response.audit.request_id,
                  "archive": response.audit.attempts[0].archive.id, "audit": response.audit.state}))
'''
    with serve(payload=payload, pause=0.15) as (base, requests):
        policy = (root / "subllm.toml").read_text().replace("enabled = true", "enabled = false")
        policy += (f'\n[custom_providers.cache_fixture]\napi_base = "{base}/v1"\n'
                   'default_model = "test-fixture-model"\npriority = 1\nenabled = true\n'
                   'routes = ["onedev-agent/code-edit"]\n')
        policy_file.write_text(policy)
        args = [sys.executable, "-c", code, str(tmp_path / "cache.sqlite3")]
        with ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(subprocess.run, args, capture_output=True, text=True, timeout=20) for _ in range(2)]
            outputs = [future.result() for future in futures]
        # A third, fresh interpreter observes the durable cache and source archive.
        outputs.append(subprocess.run(args, capture_output=True, text=True, timeout=20))
    assert all(output.returncode == 0 for output in outputs), [output.stderr for output in outputs]
    results = [json.loads(output.stdout) for output in outputs]
    assert sorted(result["state"] for result in results) == ["hit", "hit", "miss"]
    assert all(result["audit"] == "stored" for result in results)
    assert len({result["request_id"] for result in results}) == len({result["archive"] for result in results}) == 3
    assert requests == ["POST"] and count_attempts() == 1
