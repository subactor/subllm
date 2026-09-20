"""Gemini API and Anthropic Messages API transports: request mapping, error classes, failover."""
from __future__ import annotations

import io
import urllib.error

import pytest

from subllm import complete, native_http
from subllm import gemini_api as gemini
from subllm.errors import CompletionError
from subllm.native_http import NativeHTTPError

MESSAGES = [
    {"role": "system", "content": "be brief"},
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "hello"},
    {"role": "user", "content": "again"},
]
KEY = "k" * 40


def _capture(monkeypatch, module, reply):
    seen = {}

    def fake(url, body, headers, timeout, **kwargs):
        seen.update(url=url, body=body, headers=dict(headers), timeout=timeout, **kwargs)
        return reply

    monkeypatch.setattr(module, "post_json", fake)
    return seen


GEMINI_REPLY = {
    "candidates": [{"content": {"parts": [{"text": " ans"}, {"text": "wer "}]}, "finishReason": "STOP"}],
    "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3, "cachedContentTokenCount": 2},
}


def test_gemini_request_and_response_mapping(monkeypatch):
    seen = _capture(monkeypatch, gemini, GEMINI_REPLY)
    text, usage, finish = gemini.invoke(
        "https://generativelanguage.googleapis.com/v1beta", KEY, "gemini-3.8-flash", MESSAGES, 9,
        {"type": "json_object"}, {"temperature": 0.2, "max_tokens": 50})
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.8-flash:generateContent"
    assert seen["headers"] == {"x-goog-api-key": KEY}  # the key is a header, never part of the URL
    assert KEY not in seen["url"]
    assert [c["role"] for c in seen["body"]["contents"]] == ["user", "model", "user"]
    assert seen["body"]["systemInstruction"]["parts"][0]["text"].startswith("be brief")
    assert seen["body"]["generationConfig"] == {"temperature": 0.2, "maxOutputTokens": 50,
                                                "responseMimeType": "application/json"}
    assert (text, finish) == ("answer", "stop")
    assert usage == {"input_tokens": 7, "output_tokens": 3, "cached_input_tokens": 2}


def test_gemini_json_schema_and_bad_input(monkeypatch):
    seen = _capture(monkeypatch, gemini, GEMINI_REPLY)
    schema = {"type": "object"}
    gemini.invoke("https://x", KEY, "m", MESSAGES, 5, {"type": "json_schema", "json_schema": {"schema": schema}})
    assert seen["body"]["generationConfig"]["responseJsonSchema"] == schema
    with pytest.raises(CompletionError):
        gemini.invoke("https://x", KEY, "m", [{"role": "tool", "content": "x"}], 5, None)
    with pytest.raises(CompletionError):
        gemini.invoke("https://x", KEY, "m", [{"role": "user", "content": [{"type": "image_url"}]}], 5, None)
    with pytest.raises(CompletionError):
        gemini.invoke("https://x", KEY, "m", [{"role": "system", "content": "only system"}], 5, None)


@pytest.mark.parametrize("reply", [{}, {"candidates": []}, {"candidates": [{"content": {"parts": []}}]}])
def test_gemini_invalid_response_is_classified(monkeypatch, reply):
    _capture(monkeypatch, gemini, reply)
    with pytest.raises(NativeHTTPError) as exc:
        gemini.invoke("https://x", KEY, "m", MESSAGES, 5, None)
    assert exc.value.outcome == "invalid_response" and not exc.value.provider_level


def test_anthropic_request_and_response_mapping(monkeypatch):
    from subllm import anthropic_api as anthropic
    seen = _capture(monkeypatch, anthropic, {
        "content": [{"type": "text", "text": "ans"}, {"type": "tool_use"}, {"type": "text", "text": "wer"}],
        "usage": {"input_tokens": 5, "output_tokens": 2, "cache_read_input_tokens": 1}, "stop_reason": "end_turn"})
    text, usage, finish = anthropic.invoke("https://api.anthropic.com/v1", KEY, "claude-sonnet-5", MESSAGES, 9,
                                           {"type": "json_object"}, {"max_tokens": 77})
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"] == {"x-api-key": KEY, "anthropic-version": "2023-06-01"}
    assert seen["body"]["max_tokens"] == 77 and seen["body"]["model"] == "claude-sonnet-5"
    assert [m["role"] for m in seen["body"]["messages"]] == ["user", "assistant", "user"]
    assert seen["body"]["system"].startswith("be brief")
    assert (text, usage, finish) == ("answer", {"input_tokens": 5, "output_tokens": 2, "cached_input_tokens": 1},
                                     "end_turn")


class _Opener:
    def __init__(self, error=None, payload=b"{}"):
        self.error, self.payload = error, payload

    def open(self, request, timeout=None):
        if self.error:
            raise self.error
        return io.BytesIO(self.payload)


@pytest.mark.parametrize(("error", "outcome", "retryable", "provider_level"), [
    (urllib.error.HTTPError("https://x", 429, "q", {}, None), "http_429", True, True),
    (urllib.error.HTTPError("https://x", 503, "q", {}, None), "http_503", True, True),
    (urllib.error.HTTPError("https://x", 401, "q", {}, None), "http_401", True, True),
    (urllib.error.HTTPError("https://x", 404, "q", {}, None), "model_unavailable", True, False),
    (urllib.error.HTTPError("https://x", 400, "q", {}, None), "http_400", False, True),
    (urllib.error.URLError("boom"), "transport_error", True, True),
    (TimeoutError(), "timeout", True, True),
])
def test_http_failures_use_the_openai_worker_vocabulary(monkeypatch, error, outcome, retryable, provider_level):
    monkeypatch.setattr(native_http.urllib.request, "build_opener", lambda *a: _Opener(error))
    with pytest.raises(NativeHTTPError) as exc:
        native_http.post_json("https://api.example.com/x", {}, {"x-api-key": KEY}, 3)
    assert (exc.value.outcome, exc.value.retryable, exc.value.provider_level) == (outcome, retryable, provider_level)
    assert KEY not in str(exc.value)


def test_plain_http_and_oversized_or_non_json_responses_are_refused(monkeypatch):
    with pytest.raises(NativeHTTPError):
        native_http.post_json("http://insecure.example/x", {}, {}, 3)
    monkeypatch.setattr(native_http.urllib.request, "build_opener", lambda *a: _Opener(payload=b"not json"))
    with pytest.raises(NativeHTTPError) as exc:
        native_http.post_json("https://api.example.com/x", {}, {}, 3)
    assert exc.value.outcome == "invalid_response"
    monkeypatch.setattr(native_http, "MAX_RESPONSE_BYTES", 4)
    monkeypatch.setattr(native_http.urllib.request, "build_opener", lambda *a: _Opener(payload=b"{}" * 10))
    with pytest.raises(NativeHTTPError):
        native_http.post_json("https://api.example.com/x", {}, {}, 3)


def _environ(order, **keys):
    return {"PATH": "/nonexistent", "SUBLLM_PROVIDER_ORDER": order, **keys}


def test_complete_uses_gemini_when_it_is_first(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBLLM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("SUBLLM_POLICY_FILE", raising=False)
    _capture(monkeypatch, gemini, GEMINI_REPLY)
    response = complete("validator-agent", "direct-pr-review", MESSAGES, timeout_seconds=5,
                        environ=_environ("agy,openrouter", GEMINI_API_KEY=KEY, OPENROUTER_API_KEY="o" * 30))
    assert (response.provider, response.model, response.content) == ("agy", "gemini-3.8-flash", "answer")
    assert response.usage["input_tokens"] == 7


def test_quota_error_fails_over_to_the_next_provider(monkeypatch, tmp_path):
    from subllm import anthropic_api as anthropic
    monkeypatch.setenv("SUBLLM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("SUBLLM_POLICY_FILE", raising=False)

    def quota(*args, **kwargs):
        raise NativeHTTPError("http_429", status=429)

    monkeypatch.setattr(gemini, "post_json", quota)
    _capture(monkeypatch, anthropic, {"content": [{"type": "text", "text": "from claude"}], "usage": {}})
    response = complete("validator-agent", "direct-pr-review", MESSAGES, timeout_seconds=5,
                        environ=_environ("agy,claude", GEMINI_API_KEY=KEY, ANTHROPIC_API_KEY=KEY))
    assert (response.provider, response.content) == ("claude", "from claude")


def test_non_retryable_client_error_does_not_fail_over(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBLLM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("SUBLLM_POLICY_FILE", raising=False)

    def bad_request(*args, **kwargs):
        raise NativeHTTPError("http_400", status=400)

    monkeypatch.setattr(gemini, "post_json", bad_request)
    with pytest.raises(CompletionError, match="HTTP 400"):
        complete("validator-agent", "direct-pr-review", MESSAGES, timeout_seconds=5,
                 environ=_environ("agy,openrouter", GEMINI_API_KEY=KEY, OPENROUTER_API_KEY="o" * 30))


def test_gemini_503_is_model_scoped_so_another_gemini_model_is_tried(monkeypatch, tmp_path):
    monkeypatch.setenv("SUBLLM_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.delenv("SUBLLM_POLICY_FILE", raising=False)
    calls = []

    def flaky(url, body, headers, timeout, **kwargs):
        calls.append(url.rsplit("/", 1)[-1])
        if "gemini-3.8-flash" in url:
            raise NativeHTTPError("http_503", status=503, model_scoped=True)
        return GEMINI_REPLY

    monkeypatch.setattr(gemini, "post_json", flaky)
    response = complete("validator-agent", "direct-pr-review", MESSAGES, timeout_seconds=5,
                        environ=_environ("agy,openrouter", GEMINI_API_KEY=KEY, OPENROUTER_API_KEY="o" * 30))
    assert calls == ["gemini-3.8-flash:generateContent", "gemini-3.6-flash:generateContent"]
    assert (response.provider, response.model) == ("agy", "gemini-3.6-flash")


def test_only_configured_statuses_are_model_scoped(monkeypatch):
    error = urllib.error.HTTPError("https://x", 503, "q", {}, None)
    monkeypatch.setattr(native_http.urllib.request, "build_opener", lambda *a: _Opener(error))
    with pytest.raises(NativeHTTPError) as scoped:
        native_http.post_json("https://api.example.com/x", {}, {}, 3, model_scoped_statuses=frozenset({503}))
    assert scoped.value.model_scoped and not scoped.value.provider_level and scoped.value.retryable
    with pytest.raises(NativeHTTPError) as plain:
        native_http.post_json("https://api.example.com/x", {}, {}, 3)
    assert plain.value.provider_level  # other providers keep provider-wide 5xx semantics
