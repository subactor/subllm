"""CLI transports have no native JSON mode: a fenced JSON answer is not a broken model."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from subllm import claude_cli, client_routes
from subllm.client_types import _RetryableAttemptError
from subllm.quality import validate_response

OBJECT = {"verdict": "approve", "confidence": 0.9}
JSON_OBJECT = {"type": "json_object"}


def _route():
    return SimpleNamespace(transport="claude-cli", provider="claude", wire_model="claude-sonnet-5")


def _invoke(monkeypatch, content, response_format):
    monkeypatch.setattr(claude_cli, "invoke", lambda *a, **kw: (content, {}))
    return client_routes._invoke_route(_route(), [{"role": "user", "content": "x"}], timeout_seconds=5,
                                       request_id=None, response_format=response_format, cwd=None)


@pytest.mark.parametrize("content", (
    "```json\n" + json.dumps(OBJECT) + "\n```",
    "```JSON\n" + json.dumps(OBJECT, indent=2) + "\n```",
    "```\n" + json.dumps(OBJECT) + "```",
))
def test_fenced_json_object_is_unwrapped_and_passes_quality(monkeypatch, content):
    response = _invoke(monkeypatch, content, JSON_OBJECT)
    assert json.loads(response.content) == OBJECT
    assert not response.content.startswith("```")
    validate_response(response, JSON_OBJECT)


@pytest.mark.parametrize("content", (
    "Here you go:\n```json\n{\"a\": 1}\n```",
    "```json\n{\"a\": 1}\n```\n```json\n{\"b\": 2}\n```",
    "```json\nnot json\n```",
))
def test_non_whole_or_invalid_fence_is_left_for_the_quality_gate(monkeypatch, content):
    response = _invoke(monkeypatch, content, JSON_OBJECT)
    assert response.content == content
    with pytest.raises(_RetryableAttemptError, match="invalid_json"):
        validate_response(response, JSON_OBJECT)


def test_text_responses_keep_their_fences(monkeypatch):
    content = "```json\n{\"a\": 1}\n```"
    assert _invoke(monkeypatch, content, None).content == content
