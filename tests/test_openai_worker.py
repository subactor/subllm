from __future__ import annotations

import json
from urllib.error import HTTPError

import pytest

from subllm import CompletionError, openai_worker


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
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

    def open_request(request):
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


def test_execute_returns_secret_free_retryable_http_receipt(monkeypatch) -> None:
    def open_request(request):
        raise HTTPError(request.full_url, 429, "limited", {}, None)

    monkeypatch.setattr(openai_worker, "urlopen", open_request)
    result = openai_worker._execute(_source())

    assert result == {
        "schema": "subllm.openai-worker-result/v1",
        "status": "ERROR",
        "outcome": "http_429",
        "provider_level": True,
        "retryable": True,
    }
    assert "id.secret" not in repr(result)


def test_request_rejects_non_policy_provider_base() -> None:
    source = _source()
    source["api_base"] = "https://example.invalid"

    with pytest.raises(CompletionError, match="not policy-approved"):
        openai_worker._request(source)
