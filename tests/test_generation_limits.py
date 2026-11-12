from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
from test_completion_audit import call
from test_completion_audit import captured as captured
from test_http_transport_bounds import serve, source
from test_http_transport_bounds import tls_files as tls_files
from test_http_transport_bounds import trusted_loopback as trusted_loopback

from subllm import (
    CompletionError,
    CompletionResponse,
    GenerationBudget,
    GenerationLimits,
    anthropic_api,
    client_routes,
    client_workers,
    gemini_api,
    native_http,
    openai_worker,
)
from subllm.client_types import _RetryableAttemptError
from subllm.errors import InvalidPolicyError
from subllm.policy_config import load_policy_config
from subllm.usage import query_usage

ROOT = Path(__file__).resolve().parents[1]


def policy_file(tmp_path, **limits):
    text = (ROOT / "subllm.toml").read_text().replace("schema_version = 2", "schema_version = 3")
    text = re.sub(r"(?ms)^\[execution\]\n.*?(?=^\[|\Z)", "", text)
    text += ('\n[execution]\nfailover_enabled = true\nattempt_timeout_seconds = 12.0\n'
             'slow_response_seconds = 10.0\ncooldown_seconds = 0.0\nfailure_threshold = 1\nmax_attempts = 6\n')
    text += "".join(f"{key} = {json.dumps(value)}\n" for key, value in limits.items())
    path = tmp_path / "generation-policy.toml"
    path.write_text(text)
    return path


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "4", 1_000_001])
def test_invalid_public_limits_fail_before_effect(captured, value):
    with pytest.raises(CompletionError, match="invalid limit"):
        call(generation_limits={"max_output_tokens": value})
    with pytest.raises(CompletionError, match="invalid limit"):
        GenerationBudget(value)
    assert captured.calls == []


def test_closed_contract_and_unlimited_compatibility(captured):
    with pytest.raises(CompletionError, match="invalid limit"):
        call(generation_limits={"temperature": 0})
    response = call()
    assert response.generation is None and response.usage["completion_tokens"] == 2
    assert len(captured.calls) == 1 and response.audit.state == "stored"


@pytest.mark.parametrize("field,value", [("max_output_tokens", 9), ("max_total_output_tokens", 11)])
def test_caller_cannot_raise_operator_maxima(captured, monkeypatch, tmp_path, field, value):
    path = policy_file(tmp_path, max_output_tokens=8, max_total_output_tokens=10)
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(path))
    with pytest.raises(CompletionError, match="policy limit"):
        call(generation_limits={field: value})
    assert captured.calls == [] and query_usage({})["attempts"] == []


def test_lower_limits_and_operator_defaults_survive_environment_overrides(captured, monkeypatch, tmp_path):
    path = policy_file(tmp_path, max_output_tokens=8, max_total_output_tokens=10)
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(path))
    monkeypatch.setenv("SUBLLM_FAILURE_THRESHOLD", "2")
    seen = []

    def invoke(route, *args, **kwargs):
        seen.append(route.model_parameters["max_tokens"])
        return captured.invoke(route, *args, **kwargs)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    campaign = GenerationBudget(100)
    response = call(generation_limits=GenerationLimits(4, 5), generation_budget=campaign)
    assert seen == ["4"]
    assert response.generation.output_tokens == campaign.output_tokens == 2
    assert response.generation.remaining_output_tokens == 3 and campaign.remaining_tokens == 98
    with pytest.raises(FrozenInstanceError):
        response.generation.output_tokens = 0
    config = load_policy_config()
    assert config.execution.max_output_tokens == 8 and config.execution.max_total_output_tokens == 10
    second = call("operator-default-request")
    assert seen == ["4", "8"] and second.generation.remaining_output_tokens == 8


@pytest.mark.parametrize("value", [0, -1, True, "4", 1_000_001])
def test_invalid_operator_limits_fail_closed(tmp_path, value):
    path = policy_file(tmp_path, max_output_tokens=value)
    with pytest.raises(InvalidPolicyError, match="bounded integer"):
        load_policy_config(environ={"SUBLLM_POLICY_FILE": str(path)})


@pytest.mark.parametrize("transport", ["cursor-sdk", "codex-cli", "claude-cli", "agy-cli", "cursor-cli"])
def test_unsupported_transports_do_not_silently_ignore_limits(captured, monkeypatch, transport):
    route = replace(captured.route, transport=transport)
    monkeypatch.setattr(client_routes, "available_routes", lambda *args, **kwargs: [route])
    campaign = GenerationBudget(10)
    with pytest.raises(CompletionError, match="unsupported transport"):
        call(generation_limits=GenerationLimits(4), generation_budget=campaign)
    assert captured.calls == [] and campaign.remaining_tokens == 10 and campaign.output_tokens == 0
    assert query_usage({})["attempts"] == []


def test_quality_rejection_spends_remaining_budget_and_preserves_native_usage(captured, monkeypatch):
    routes = [replace(captured.route, wire_model=f"test-model-{index}") for index in range(2)]
    monkeypatch.setattr(client_routes, "available_routes", lambda *args, **kwargs: routes)
    caps = []

    def invoke(route, *args, **kwargs):
        caps.append(int(route.model_parameters["max_tokens"]))
        count = 3 if len(caps) == 1 else 2
        return CompletionResponse("bad" if len(caps) == 1 else "ok", route.provider, route.wire_model,
                                  {"output_tokens": count}, "stop")

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    budget = GenerationBudget(5)
    response = call(generation_limits=GenerationLimits(4, 5), generation_budget=budget,
                    quality_gate=lambda result: result.content == "ok")
    assert caps == [4, 2] and response.content == "ok"
    assert response.generation.output_tokens == budget.output_tokens == 5
    assert response.generation.attempts == 2 and budget.remaining_tokens == 0
    assert [a.status for a in response.audit.attempts] == ["error", "success"]
    assert sum(row["output_tokens"] for row in query_usage({})["attempts"]) == 5


@pytest.mark.parametrize("finish", ["length", "max_tokens", "max_output_tokens"])
def test_partial_response_spends_tokens_without_success_or_extra_call(captured, monkeypatch, finish):
    monkeypatch.setattr(client_routes, "available_routes", lambda *args, **kwargs: [captured.route] * 2)
    seen = []

    def invoke(route, *args, **kwargs):
        seen.append(int(route.model_parameters["max_tokens"]))
        return CompletionResponse("partial", route.provider, route.wire_model, {"output_tokens": 4}, finish)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    budget = GenerationBudget(4)
    with pytest.raises(CompletionError, match="budget exhausted"):
        call(generation_limits=GenerationLimits(4), generation_budget=budget)
    assert seen == [4] and budget.output_tokens == 4 and budget.remaining_tokens == 0
    row, = query_usage({})["attempts"]
    assert row["status"] == "error" and row["output_tokens"] == 4


@pytest.mark.parametrize("reported", [{}, {"output_tokens": True}, {"output_tokens": -1},
                                     {"output_tokens": 2, "completion_tokens": 3}])
def test_unknown_usage_is_not_zero_and_blocks_future_campaign_dispatch(captured, monkeypatch, reported):
    def invoke(route, *args, **kwargs):
        captured.calls.append(1)
        return CompletionResponse("ok", route.provider, route.wire_model, reported)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    budget = GenerationBudget(5)
    response = call(generation_budget=budget)
    assert response.generation.output_tokens is budget.output_tokens is budget.remaining_tokens is None
    with pytest.raises(CompletionError, match="usage unknown"):
        call("next-request", generation_budget=budget)
    assert len(captured.calls) == 1


def test_transport_failure_never_assumes_a_free_retry(captured, monkeypatch):
    monkeypatch.setattr(client_routes, "available_routes", lambda *args, **kwargs: [captured.route] * 2)

    def invoke(*args, **kwargs):
        captured.calls.append(1)
        raise _RetryableAttemptError("test-only lost response", outcome="timeout", provider_level=False)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    budget = GenerationBudget(5)
    with pytest.raises(CompletionError, match="usage unknown"):
        call(generation_budget=budget)
    assert captured.calls == [1] and budget.output_tokens is None
    assert query_usage({})["attempts"][0]["output_tokens"] is None


def test_provider_overrun_is_accounted_but_not_successful(captured, monkeypatch):
    def invoke(route, *args, **kwargs):
        captured.calls.append(1)
        return CompletionResponse("overrun", route.provider, route.wire_model, {"output_tokens": 6})

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    budget = GenerationBudget(5)
    with pytest.raises(CompletionError, match="limit exceeded"):
        call(generation_budget=budget)
    assert captured.calls == [1] and budget.output_tokens == 6 and budget.remaining_tokens == 0
    assert query_usage({})["attempts"][0]["status"] == "error"


def test_campaign_reservations_bound_concurrent_requests(captured, monkeypatch):
    barrier = threading.Barrier(2, timeout=10)
    caps = []

    def invoke(route, *args, **kwargs):
        cap = int(route.model_parameters["max_tokens"])
        caps.append(cap)
        barrier.wait()
        return CompletionResponse("ok", route.provider, route.wire_model, {"output_tokens": cap})

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    budget = GenerationBudget(10)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda i: call(f"parallel-{i}", generation_limits=GenerationLimits(6),
                                              generation_budget=budget), range(2)))
    assert sorted(caps) == [4, 6] and budget.output_tokens == 10 and budget.remaining_tokens == 0
    assert sum(result.generation.output_tokens for result in results) == 10
    assert len({result.audit.attempts[0].archive.id for result in results}) == 2
    with pytest.raises(CompletionError, match="budget exhausted"):
        call("after-campaign", generation_budget=budget)
    assert len(caps) == 2


def test_confirmed_zero_usage_releases_the_reservation(captured, monkeypatch):
    monkeypatch.setattr(client_routes, "_invoke_route", lambda route, *a, **kw:
                        CompletionResponse("ok", route.provider, route.wire_model, {"output_tokens": 0}))
    budget = GenerationBudget(5)
    response = call(generation_budget=budget)
    assert response.generation.output_tokens == budget.output_tokens == 0 and budget.remaining_tokens == 5


def test_private_dispatch_requires_a_request_scope_for_a_total_policy_limit(captured, monkeypatch, tmp_path):
    path = policy_file(tmp_path, max_total_output_tokens=5)
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(path))
    with pytest.raises(CompletionError, match="request scope required"):
        client_routes._complete_route(captured.route, [{"role": "user", "content": "fixture"}],
                                      timeout_seconds=5, request_id="private-request", response_format=None,
                                      cwd=tmp_path, policy_file=path)
    assert captured.calls == [] and query_usage({})["attempts"] == []


@pytest.mark.parametrize("limit", ["0", "true", '"5"', "1000001"])
def test_invalid_custom_provider_limits_are_rejected(tmp_path, limit):
    text = (ROOT / "subllm.toml").read_text()
    text += ('\n[custom_providers.generation_fixture]\napi_base = "http://127.0.0.1:8000/v1"\n'
             'default_model = "fixture-model"\n[custom_providers.generation_fixture.model_parameters]\n'
             f'max_tokens = {limit}\n')
    path = tmp_path / "invalid-custom.toml"
    path.write_text(text)
    with pytest.raises(InvalidPolicyError, match="model_parameters.max_tokens"):
        load_policy_config(environ={"SUBLLM_POLICY_FILE": str(path)})


@pytest.mark.parametrize("meta,expected", [
    ({"promptTokenCount": 3, "candidatesTokenCount": 2, "thoughtsTokenCount": 1}, 3),
    ({"promptTokenCount": 3, "candidatesTokenCount": 2, "totalTokenCount": 6}, 3),
    ({"promptTokenCount": 3, "candidatesTokenCount": 2}, None),
    ({"promptTokenCount": 3, "candidatesTokenCount": 2, "thoughtsTokenCount": 1, "totalTokenCount": 5}, None),
    ({"promptTokenCount": 3, "candidatesTokenCount": 2, "totalTokenCount": 3}, None),
    ({"promptTokenCount": 3, "candidatesTokenCount": 2, "thoughtsTokenCount": True, "totalTokenCount": 6}, None),
])
def test_gemini_thinking_usage_is_counted_or_explicitly_unknown(
    captured, monkeypatch, tls_files, trusted_loopback, meta, expected,
):
    reply = {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
             "usageMetadata": meta}
    with serve(tls_files, payload=json.dumps(reply).encode()) as (base, requests):
        route = replace(captured.route, transport="gemini-sdk", api_base=base)
        monkeypatch.setattr(client_routes, "available_routes", lambda *a, **kw: [route])

        def invoke(route, messages, *, timeout_seconds, response_format, **kwargs):
            return client_routes._complete_native(route, messages, timeout_seconds=timeout_seconds,
                                                   response_format=response_format)

        monkeypatch.setattr(client_routes, "_invoke_route", invoke)
        budget = GenerationBudget(7)
        response = call(generation_budget=budget)
    assert requests == ["POST"] and response.content == "ok"
    assert response.generation.output_tokens == budget.output_tokens == expected
    assert budget.remaining_tokens == (None if expected is None else 7 - expected)
    assert query_usage({})["attempts"][0]["output_tokens"] == expected


@pytest.mark.parametrize("protocol", ["openai", "openai-reasoning", "anthropic", "gemini"])
def test_native_wire_limits_are_exact_integers_over_real_http(monkeypatch, tls_files, trusted_loopback, protocol):
    replies = {
        "openai": {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                   "usage": {"prompt_tokens": 3, "completion_tokens": 2}},
        "anthropic": {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn",
                      "usage": {"input_tokens": 3, "output_tokens": 2}},
        "gemini": {"candidates": [{"content": {"parts": [{"text": "ok"}]}, "finishReason": "STOP"}],
                   "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2,
                                     "thoughtsTokenCount": 1, "totalTokenCount": 6}},
    }
    reply = replies["openai" if protocol.startswith("openai") else protocol]
    bodies = []
    with serve(tls_files, payload=json.dumps(reply).encode()) as (base, requests):
        if protocol.startswith("openai"):
            original = openai_worker.urlopen

            def observe(request, **kwargs):
                bodies.append(json.loads(request.data))
                return original(request, **kwargs)

            monkeypatch.setattr(openai_worker, "urlopen", observe)
            request = {**source(base), "max_tokens": 7, "model_parameters": {"max_tokens": "7"},
                       "request_fields": {"user_id": "test-attribution"}}
            if protocol == "openai-reasoning":
                request["provider"] = "codex"
            assert openai_worker._execute(request)["content"] == "ok"
        else:
            module = anthropic_api if protocol == "anthropic" else gemini_api
            original = native_http.post_json

            def observe(url, body, *args, **kwargs):
                bodies.append(body)
                return original(url, body, *args, **kwargs)

            monkeypatch.setattr(module, "post_json", observe)
            content, usage, _ = module.invoke(base, "test-only-credential", "test-model",
                                             [{"role": "user", "content": "fixture"}], 5, None,
                                             {"max_tokens": "7"})
            assert content == "ok"
            if protocol == "gemini":
                assert usage["output_tokens"] == 3
        assert requests == ["POST"]
    body, = bodies
    if protocol == "gemini":
        assert body["generationConfig"]["maxOutputTokens"] == 7
    else:
        key = "max_completion_tokens" if protocol == "openai-reasoning" else "max_tokens"
        assert body[key] == 7 and type(body[key]) is int
        assert ("max_tokens" if key == "max_completion_tokens" else "max_completion_tokens") not in body
        if protocol.startswith("openai"):
            assert body["user_id"] == "test-attribution"


def test_public_limits_reach_real_child_worker_and_custom_policy(monkeypatch, tmp_path):
    from subllm import complete, interaction_store

    monkeypatch.setattr(interaction_store, "_DEFAULT_STORE", None)
    monkeypatch.setenv("SUBLLM_ARCHIVE_DIR", str(tmp_path / "archive"))
    payload = json.dumps({"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": 3, "completion_tokens": 2}}).encode()
    worker_requests = []
    original = client_workers._run_openai_worker

    def observe(request, **kwargs):
        worker_requests.append(request)
        return original(request, **kwargs)

    monkeypatch.setattr(client_workers, "_run_openai_worker", observe)
    with serve(payload=payload) as (base, requests):
        text = (ROOT / "subllm.toml").read_text().replace("enabled = true", "enabled = false")
        text += (f'\n[custom_providers.generation_fixture]\napi_base = "{base}/v1"\n'
                 'default_model = "fixture-model"\npriority = 1\nenabled = true\n'
                 'routes = ["onedev-agent/code-edit"]\n'
                 '[custom_providers.generation_fixture.model_parameters]\nmax_tokens = 6\n')
        path = tmp_path / "subllm.toml"
        path.write_text(text)
        monkeypatch.setenv("SUBLLM_POLICY_FILE", str(path))
        response = complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}],
                            generation_limits=GenerationLimits(4, 5), timeout_seconds=10)
    assert requests == ["POST"] and response.content == "ok"
    request, = worker_requests
    assert request["max_tokens"] == 4 and request["model_parameters"]["max_tokens"] == "4"
    assert response.generation.output_tokens == 2 and response.generation.remaining_output_tokens == 3
    assert response.audit.state == "stored"
