from __future__ import annotations

import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from subllm import CompletionError, openai_worker


@pytest.mark.parametrize("code", ["credit_balance_exhausted", "insufficient_quota",
    "project_spend_limit_exceeded", "organization_spend_limit_exceeded",
    "organization_usage_limit_exceeded", "billing_hard_limit_reached"])
def test_billing_429_is_exhausted_quota_without_leaking_provider_text(monkeypatch, code):
    payload = json.dumps({"error": {"type": "insufficient_quota", "code": code,
                                    "message": "private account id.secret"}}).encode()
    def invoke(request, **_kwargs):
        raise HTTPError(request.full_url, 429, "limited", {}, BytesIO(payload))
    monkeypatch.setattr(openai_worker, "urlopen", invoke)
    result = openai_worker._execute(_source())
    assert result["outcome"] == "quota_exhausted"
    assert result["retryable"] is True  # another authorized transport may serve
    assert result["provider_level"] is True
    assert "private account" not in repr(result) and "id.secret" not in repr(result)


def test_temporary_429_remains_a_rate_limit(monkeypatch):
    payload = json.dumps({"error": {"type": "rate_limit_error", "code": "rate_limit_exceeded"}}).encode()
    def invoke(request, **_kwargs):
        raise HTTPError(request.full_url, 429, "limited", {}, BytesIO(payload))
    monkeypatch.setattr(openai_worker, "urlopen", invoke)
    assert openai_worker._execute(_source())["outcome"] == "http_429"


@pytest.mark.parametrize(("provider", "code", "expected"), [
    ("zai", "1310", "quota_exhausted"),
    ("zai", "1302", "http_429"),
    ("codex", "1310", "http_429"),
    (None, "1310", "http_429"),
    ("zai", ["1310"], "http_429"),
])
def test_zai_plan_limit_is_provider_specific_and_secret_free(monkeypatch, provider, code, expected):
    payload = json.dumps({"error": {"code": code,
        "message": "Weekly/Monthly Limit Exhausted; private account id.secret"}}).encode()

    def invoke(request, **_kwargs):
        raise HTTPError(request.full_url, 429, "limited", {}, BytesIO(payload))

    monkeypatch.setattr(openai_worker, "urlopen", invoke)
    source = _source()
    if provider is None:
        source.pop("provider")  # Private exchange callers may omit routing metadata.
    else:
        source["provider"] = provider
    result = openai_worker._execute(source)
    assert result["outcome"] == expected
    assert result["retryable"] and result["provider_level"]
    assert "private account" not in repr(result) and "id.secret" not in repr(result)


@pytest.mark.parametrize("error", [[], {"code": ["credit_balance_exhausted"]}, {"code": {}}])
def test_malformed_quota_evidence_remains_a_bounded_http_failure(monkeypatch, error):
    payload = json.dumps({"error": error}).encode()
    def invoke(request, **_kwargs):
        raise HTTPError(request.full_url, 429, "limited", {}, BytesIO(payload))
    monkeypatch.setattr(openai_worker, "urlopen", invoke)
    assert openai_worker._execute(_source())["outcome"] == "http_429"


def test_oversized_429_body_cannot_supply_quota_evidence(monkeypatch):
    payload = b" " * 1_000_001 + b'{"error":{"code":"credit_balance_exhausted"}}'
    def invoke(request, **_kwargs):
        raise HTTPError(request.full_url, 429, "limited", {}, BytesIO(payload))
    monkeypatch.setattr(openai_worker, "urlopen", invoke)
    assert openai_worker._execute(_source())["outcome"] == "http_429"


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, size: int = -1) -> bytes:
        return json.dumps({
            "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}],
            "usage": {"total_tokens": 9},
        }).encode("utf-8")


def _source() -> dict[str, object]:
    return {
        "schema": "subllm.openai-worker-request/v1",
        "provider": "zai",
        "api_base": "https://api.z.ai/api/coding/paas/v4",
        "wire_model": "glm-5.3",
        "api_key": "id.secret",
        "messages": [{"role": "user", "content": "assess"}],
        "model_parameters": {},
        "request_fields": {"request_id": "worker-test-0001", "user_id": "supervisor"},
        "extra_headers": {},
        "response_format": {"type": "json_object"},
    }


def test_execute_preserves_policy_owned_request_fields(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def open_request(request, **_kwargs):
        observed["url"] = request.full_url
        observed["authorization"] = request.get_header("Authorization")
        observed["body"] = json.loads(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr(openai_worker, "urlopen", open_request)
    result = openai_worker._execute(_source())

    assert result == {
        "schema": "subllm.openai-worker-result/v1",
        "status": "SUCCESS",
        "content": '{"ok":true}',
        "usage": {"total_tokens": 9},
        "finish_reason": "stop",
    }
    assert observed["url"] == "https://api.z.ai/api/coding/paas/v4/chat/completions"
    assert observed["authorization"] == "Bearer id.secret"
    assert observed["body"]["model"] == "glm-5.3"
    assert observed["body"]["request_id"] == "worker-test-0001"
    assert observed["body"]["response_format"] == {"type": "json_object"}
    assert "id.secret" not in repr(result)


@pytest.mark.parametrize("status", [402, 429])
def test_execute_returns_secret_free_retryable_http_receipt(monkeypatch, status) -> None:
    def open_request(request, **_kwargs):
        raise HTTPError(request.full_url, status, "limited", {}, None)

    monkeypatch.setattr(openai_worker, "urlopen", open_request)
    result = openai_worker._execute(_source())

    assert result == {
        "schema": "subllm.openai-worker-result/v1",
        "status": "ERROR",
        "outcome": f"http_{status}",
        "provider_level": True,
        "retryable": True,
    }
    assert "id.secret" not in repr(result)


def test_request_rejects_non_policy_provider_base() -> None:
    source = _source()
    source["api_base"] = "https://example.invalid"

    with pytest.raises(CompletionError, match="not policy-approved"):
        openai_worker._request(source)


@pytest.mark.parametrize("status", [400, 422])
def test_invalid_request_remains_terminal(monkeypatch, status) -> None:
    def open_request(request, **_kwargs):
        raise HTTPError(request.full_url, status, "invalid request", {}, None)

    monkeypatch.setattr(openai_worker, "urlopen", open_request)
    result = openai_worker._execute(_source())
    assert result["retryable"] is False
    assert result["outcome"] == f"http_{status}"


def test_execute_applies_timeout_to_urlopen(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def open_request(request, **kwargs):
        observed["timeout"] = kwargs.get("timeout")
        return _Response()

    monkeypatch.setattr(openai_worker, "urlopen", open_request)
    source = _source()
    source["timeout_seconds"] = 15.5
    result = openai_worker._execute(source)

    assert result["status"] == "SUCCESS"
    assert observed["timeout"] == 15.5


def test_execute_handles_socket_timeout(monkeypatch) -> None:
    def open_request(request, **_kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr(openai_worker, "urlopen", open_request)
    source = _source()
    source["timeout_seconds"] = 5.0
    result = openai_worker._execute(source)

    assert result == {
        "schema": "subllm.openai-worker-result/v1",
        "status": "ERROR",
        "outcome": "timeout",
        "provider_level": True,
        "retryable": True,
    }


def test_execute_handles_max_tokens_in_source_and_model_params(monkeypatch) -> None:
    observed_bodies: list[dict[str, object]] = []

    def open_request(request, **_kwargs):
        observed_bodies.append(json.loads(request.data.decode("utf-8")))
        return _Response()

    monkeypatch.setattr(openai_worker, "urlopen", open_request)

    # 1. Via top-level max_tokens
    s1 = _source()
    s1["max_tokens"] = 2048
    openai_worker._execute(s1)
    assert observed_bodies[-1]["max_tokens"] == 2048

    # 2. Via string in model_parameters
    s2 = _source()
    s2["model_parameters"] = {"max_tokens": "4096"}
    openai_worker._execute(s2)
    assert observed_bodies[-1]["max_tokens"] == 4096


def test_execute_handles_reasoning_truncation(monkeypatch) -> None:
    class _ReasoningResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size: int = -1) -> bytes:
            return json.dumps({
                "choices": [{
                    "message": {
                        "content": "",
                        "reasoning_content": "Deep thought process that took too many tokens...",
                    },
                    "finish_reason": "length",
                }],
                "usage": {
                    "total_tokens": 128,
                    "completion_tokens_details": {"reasoning_tokens": 120},
                },
            }).encode("utf-8")

    def open_request(request, **_kwargs):
        return _ReasoningResponse()

    monkeypatch.setattr(openai_worker, "urlopen", open_request)
    result = openai_worker._execute(_source())

    assert result["status"] == "ERROR"
    assert result["outcome"] == "truncated"
    assert result["provider_level"] is True
    assert result["retryable"] is True
    assert "120 tokens" in result["message"]
    assert result["usage"]["total_tokens"] == 128
