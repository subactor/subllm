from __future__ import annotations

import json
import threading
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from subllm.decisions import DecisionError, decide, decide_legacy
from subllm.usage import query_usage


def questions():
    return {
        "route": {"type": "choice", "instructions": "Which operation?",
                  "criteria": {"read": "Inspect status", "write": "Restart service"}},
        "allowed": {"type": "noul", "instructions": "Is a mutation requested?"},
        "risk": {"type": "score", "instructions": "How risky?", "criteria": ["low", "medium", "high"]},
    }


def reply():
    return {"model": "d1:3b", "usage": {"input_tokens": 12, "output_tokens": 0}, "answers": {
        "route": {"type": "choice", "choice": "read", "probabilities": {"read": 0.9, "write": 0.1}},
        "allowed": {"type": "noul", "noul": 0.1},
        "risk": {"type": "score", "score": 0.3, "probabilities": {"0": 0.8, "1": 0.1, "2": 0.1}},
    }}


@pytest.fixture
def native_server():
    state = SimpleNamespace(reply=reply(), status=200, requests=[], raw=None)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            state.requests.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(state.status)
            if state.status == 307:
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/api/chat")
            self.end_headers()
            self.wfile.write(state.raw if state.raw is not None else json.dumps(state.reply).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    state.base_url = f"http://127.0.0.1:{server.server_port}"
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_real_http_native_contract_ignores_proxy_environment(native_server, monkeypatch):
    for key in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(key, "http://127.0.0.1:1")
    monkeypatch.setenv("no_proxy", "")
    monkeypatch.setenv("NO_PROXY", "")
    result = decide({"query": "PRIVATE STATUS REQUEST"}, questions(), base_url=native_server.base_url,
                    application="willmux", function="decision-routing", request_id="native-case")
    assert result == reply()
    assert native_server.requests == [("/v1/systemone", {
        "model": "d1:3b", "state": {"query": "PRIVATE STATUS REQUEST"}, "questions": questions(), "keep_alive": 90})]
    row = query_usage({"limit": 1})["attempts"][0]
    assert row["request_id"] != "native-case" and row["application"] == "willmux"
    assert row["function"] == "decision-routing"
    assert row["provider"] == "ollama" and row["model"] == "d1:3b"
    assert row["input_tokens"] == 12 and row["output_tokens"] == 0


@pytest.mark.parametrize("candidate_url", ["https://example.com", "http://10.0.0.1:11434", "http://[::]:11434",
                                     "http://127.0.0.1/api", "http://user:pass@127.0.0.1", "http://127.0.0.1?key=x",
                                     "http://127.0.0.1#fragment", "file:///tmp/model", "http://127.0.0.1:0"])
def test_nonlocal_or_ambiguous_origin_rejected_before_transport(candidate_url, monkeypatch):
    monkeypatch.setattr("subllm.decisions._post", lambda *a: pytest.fail("Invalid origin reached inference"))
    with pytest.raises(ValueError, match="loopback"):
        decide("state", questions(), base_url=candidate_url)


@pytest.mark.parametrize("model", ["d1:cloud", "qwen3.5:0.8b", "other/d1:3b", "d1-ultra:latest"])
def test_model_is_not_aliased_or_routed_to_other_inference(model, native_server):
    with pytest.raises(ValueError, match="supported names are"):
        decide("state", questions(), model=model, base_url=native_server.base_url)
    assert not native_server.requests


@pytest.mark.parametrize("model", ["d1-ultra", "d1:3b"])
def test_served_local_decision_models_are_accepted_unaliased(model, native_server):
    native_server.reply = {"model": model, "usage": {"input_tokens": 5, "output_tokens": 0},
                           "answers": {"q": {"type": "noul", "noul": 0.93}}}
    result = decide("state", {"q": {"type": "noul", "instructions": "diagnose"}}, model=model,
                    base_url=native_server.base_url)
    assert result["model"] == model
    assert native_server.requests[0][1]["model"] == model


def test_environment_config_uses_exact_local_origin_and_normalizes_only_d1_alias(native_server, monkeypatch):
    monkeypatch.setenv("SUBLLM_DECISION_BASE_URL", native_server.base_url)
    monkeypatch.setenv("SUBLLM_DECISION_MODEL", "d1")
    assert decide("state", questions())["model"] == "d1:3b"
    assert len(native_server.requests) == 1


@pytest.mark.parametrize("invalid", [None, {}, {"a": {"type": "generate", "instructions": "text"}},
                                    {"a": {"type": "choice", "instructions": "text", "criteria": {"only": None}}},
                                    {"a": {"type": "score", "instructions": "text", "criteria": ["one"]}},
                                    {"a": {"type": "noul", "instructions": "text", "temperature": 1}}])
def test_invalid_questions_do_not_run_inference(native_server, invalid):
    with pytest.raises(ValueError):
        decide("state", invalid, base_url=native_server.base_url)
    assert not native_server.requests


@pytest.mark.parametrize("kwargs", [{"timeout_seconds": True}, {"timeout_seconds": float("inf")},
                                   {"timeout_seconds": 301}, {"keep_alive": -1}, {"keep_alive": True}])
def test_invalid_budget_does_not_run_inference(native_server, kwargs):
    with pytest.raises(ValueError):
        decide("state", questions(), base_url=native_server.base_url, **kwargs)
    assert not native_server.requests


def test_oversized_state_does_not_run_inference(native_server):
    with pytest.raises(ValueError, match="size bound"):
        decide("x" * 262144, questions(), base_url=native_server.base_url)
    assert not native_server.requests


@pytest.mark.parametrize(("path", "value"), [
    (("model",), "other-model"), (("usage",), {}), (("usage", "input_tokens"), None),
    (("usage", "output_tokens"), 1), (("usage", "output_tokens"), False),
    (("answers",), {}), (("answers", "route", "choice"), "injected-operation"),
    (("answers", "route", "choice"), "write"), (("answers", "route", "type"), "score"),
    (("answers", "route", "probabilities"), {"read": 0.8, "write": 0.8}),
    (("answers", "route", "probabilities"), {"read": True, "write": False}),
    (("answers", "route", "probabilities"), {"read": "0.9", "write": 0.1}),
    (("answers", "route", "probabilities"), {"read": float("nan"), "write": 0.1}),
    (("answers", "route", "probabilities"), {"read": 1.0, "injected": 0.0}),
    (("answers", "risk", "score"), 1.7), (("answers", "allowed", "noul"), 2),
])
def test_malformed_answers_are_rejected_without_retry(native_server, path, value):
    target = native_server.reply
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(DecisionError):
        decide("state", questions(), base_url=native_server.base_url)
    assert len(native_server.requests) == 1
    row = query_usage({"limit": 1})["attempts"][0]
    assert row["status"] == "error" and row["output_tokens"] is None


@pytest.mark.parametrize("status", [307, 429, 503])
def test_redirect_and_http_errors_never_follow_or_fallback(native_server, status):
    native_server.status = status
    with pytest.raises(DecisionError):
        decide("state", questions(), base_url=native_server.base_url)
    assert len(native_server.requests) == 1
    assert native_server.requests[0][0] == "/v1/systemone"


@pytest.mark.parametrize("raw", [b'{"model":"d1:3b","model":"other"}', b"not-json", b"x" * 1048577])
def test_duplicate_keys_invalid_json_and_oversized_response_are_rejected(native_server, raw):
    native_server.raw = raw
    with pytest.raises(DecisionError):
        decide("state", questions(), base_url=native_server.base_url)
    assert len(native_server.requests) == 1


def test_native_timeout_is_reported_once_without_replay(monkeypatch):
    calls = []

    class Unavailable:
        def open(self, request, **kwargs):
            calls.append(kwargs)
            raise TimeoutError("PRIVATE upstream failure")

    monkeypatch.setattr("subllm.decisions.build_opener", lambda *a: Unavailable())
    with pytest.raises(DecisionError, match="unavailable") as caught:
        decide("state", questions(), timeout_seconds=120)
    assert caught.value.outcome == "timeout"
    assert calls == [{"timeout": 120}]


def test_legacy_adapter_preserves_descriptions_score_labels_and_metadata(native_server):
    native_server.reply = {"model": "d1:3b", "usage": {"input_tokens": 8, "output_tokens": 0}, "answers": {
        "risk": {"type": "score", "score": 0.3, "probabilities": {"0": 0.8, "1": 0.1, "2": 0.1}},
    }}
    payload = {"model": "d1:3b", "state": {"query": "read"}, "questions": [
        {"id": "risk", "type": "score", "question": "Risk?", "options": {"1": "Low", "2": "Medium", "3": "High"}}]}
    original = deepcopy(payload)
    result = decide_legacy(payload, application="willmux", function="decision-routing", base_url=native_server.base_url)
    assert result["probabilities"]["risk"] == {"1": 0.8, "2": 0.1, "3": 0.1}
    assert result["answers"]["risk"] == pytest.approx(1.3)
    assert native_server.requests[0][1]["questions"]["risk"]["criteria"] == ["Low", "Medium", "High"]
    assert payload == original
    assert result["model"] == "d1:3b" and result["usage"]["output_tokens"] == 0


def test_legacy_invalid_question_is_not_silently_dropped(native_server):
    with pytest.raises(ValueError):
        decide_legacy({"questions": [{"id": "bad", "type": "choice", "options": ["a", "b"]}, None]},
                      base_url=native_server.base_url)
    assert not native_server.requests


@pytest.mark.parametrize("labels", [["low", "medium", "high"], ["nan", "inf", "-inf"]])
def test_legacy_nonnumeric_score_labels_preserve_finite_native_level(native_server, labels):
    native_server.reply["answers"] = {"risk": native_server.reply["answers"]["risk"]}
    result = decide_legacy({"state": "inspect", "questions": [
        {"id": "risk", "type": "score", "question": "Risk?", "options": labels}]},
        base_url=native_server.base_url)
    assert result["answers"]["risk"] == pytest.approx(0.3)
    assert set(result["probabilities"]["risk"]) == set(labels)
