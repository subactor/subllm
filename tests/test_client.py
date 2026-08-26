from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from subllm import CompletionError, client, complete


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_complete_executes_direct_zai_glm53_route(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def open_request(request, *, timeout):
        observed["url"] = request.full_url
        observed["authorization"] = request.get_header("Authorization")
        observed["body"] = json.loads(request.data.decode("utf-8"))
        observed["timeout"] = timeout
        return _Response(
            {
                "choices": [
                    {"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}
                ],
                "usage": {"total_tokens": 9},
            }
        )

    monkeypatch.setattr(client, "urlopen", open_request)
    result = complete(
        "todo2code",
        "semantic",
        [{"role": "user", "content": "Classify this change"}],
        request_id="todo2code-test-0001",
        timeout_seconds=12,
        environ={"ZAI_API_KEY": "id.secret"},
    )

    assert result.content == '{"ok":true}'
    assert result.provider == "zai"
    assert result.model == "glm-5.3"
    assert result.usage == {"total_tokens": 9}
    assert observed["url"] == "https://api.z.ai/api/coding/paas/v4/chat/completions"
    assert observed["authorization"] == "Bearer id.secret"
    assert observed["timeout"] == 12
    assert observed["body"] == {
        "model": "glm-5.3",
        "messages": [{"role": "user", "content": "Classify this change"}],
        "request_id": "todo2code-test-0001",
        "user_id": "todo2code",
    }
    assert "id.secret" not in repr(result)


def test_complete_rejects_non_openai_transport(monkeypatch) -> None:
    monkeypatch.setattr(
        client,
        "resolve",
        lambda *_args, **_kwargs: SimpleNamespace(
            provider="cursor",
            transport="cursor-sdk",
        ),
    )

    with pytest.raises(CompletionError, match="only executes openai-compatible routes"):
        complete("koru-agent", "planning-assistant", [{"role": "user", "content": "x"}])


def test_complete_rejects_empty_messages() -> None:
    with pytest.raises(CompletionError, match="at least one message"):
        complete("todo2code", "semantic", [], environ={"ZAI_API_KEY": "id.secret"})
