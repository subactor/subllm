from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import subllm.proxy as proxy
from subllm import CompletionResponse, make_proxy_server


@pytest.fixture
def proxy_server(monkeypatch):
    """Start proxy server on ephemeral port."""
    server = make_proxy_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base_url = f"http://127.0.0.1:{port}"
    try:
        yield base_url, server
    finally:
        server.shutdown()
        server.server_close()


def _request(method: str, url: str, payload: dict | None = None, headers: dict | None = None) -> tuple[int, dict, dict]:
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(url, data=data, headers=req_headers, method=method)
    try:
        with urlopen(req, timeout=5) as resp:
            body = resp.read().decode()
            resp_headers = dict(resp.headers)
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"raw": body}
            return resp.status, parsed, resp_headers
    except HTTPError as exc:
        body = exc.read().decode()
        resp_headers = dict(exc.headers)
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = {"raw": body}
        return exc.code, parsed, resp_headers


def test_proxy_health_and_cors(proxy_server):
    base_url, _ = proxy_server
    status, body, headers = _request("GET", f"{base_url}/health")
    assert status == 200
    assert body["status"] == "ok"
    assert body["service"] == "subllm-proxy"
    assert "access-control-allow-origin" in [k.lower() for k in headers]


def test_proxy_options_cors(proxy_server):
    base_url, _ = proxy_server
    status, _, headers = _request("OPTIONS", f"{base_url}/v1/chat/completions")
    assert status == 204
    assert any(k.lower() == "access-control-allow-methods" for k in headers)


def test_proxy_models_openai(proxy_server):
    base_url, _ = proxy_server
    status, body, _ = _request("GET", f"{base_url}/v1/models")
    assert status == 200
    assert body["object"] == "list"
    model_ids = {m["id"] for m in body["data"]}
    assert "glm-5.3" in model_ids
    assert "gpt-5.6-sol" in model_ids
    assert "deepseek-v4-pro" in model_ids
    assert "koru-agent/queue-executor" in model_ids


def test_proxy_tags_ollama(proxy_server):
    base_url, _ = proxy_server
    status, body, _ = _request("GET", f"{base_url}/api/tags")
    assert status == 200
    models = body["models"]
    model_names = {m["name"] for m in models}
    assert "glm-5.3:latest" in model_names
    glm_entry = next(m for m in models if m["name"] == "glm-5.3:latest")
    assert glm_entry["details"]["family"] == "glm"


def test_proxy_version_ollama(proxy_server):
    base_url, _ = proxy_server
    status, body, _ = _request("GET", f"{base_url}/api/version")
    assert status == 200
    assert "version" in body


def test_proxy_show_ollama(proxy_server):
    base_url, _ = proxy_server
    status, body, _ = _request("POST", f"{base_url}/api/show", {"name": "glm-5.3"})
    assert status == 200
    assert "modelfile" in body
    assert body["details"]["family"] == "glm"


def test_proxy_openai_chat_completions_non_streaming(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    fake_response = CompletionResponse(
        content="SubLLM proxy generated answer",
        provider="zai",
        model="glm-5.3",
        usage={"input_tokens": 12, "output_tokens": 8},
        finish_reason="stop",
    )
    monkeypatch.setattr(proxy, "_complete_model_direct", lambda *args, **kwargs: fake_response)

    payload = {
        "model": "glm-5.3@ticket-008",
        "messages": [{"role": "user", "content": "How does subllm work?"}],
        "stream": False,
    }
    status, body, headers = _request("POST", f"{base_url}/v1/chat/completions", payload)
    assert status == 200
    assert body["object"] == "chat.completion"
    assert body["model"] == "glm-5.3"
    assert body["choices"][0]["message"]["content"] == "SubLLM proxy generated answer"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"]["prompt_tokens"] == 12
    assert body["usage"]["completion_tokens"] == 8
    assert headers.get("X-Subactor-Provider") == "zai"
    assert headers.get("X-Subactor-Ticket") == "ticket-008"


def test_proxy_openai_chat_completions_streaming(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    fake_response = CompletionResponse(
        content="Hello world",
        provider="zai",
        model="glm-5.3",
        usage={"input_tokens": 5, "output_tokens": 2},
        finish_reason="stop",
    )
    monkeypatch.setattr(proxy, "_complete_model_direct", lambda *args, **kwargs: fake_response)

    payload = {
        "model": "glm-5.3",
        "messages": [{"role": "user", "content": "Hi"}],
        "stream": True,
    }
    req = Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=5) as resp:
        assert resp.status == 200
        assert "text/event-stream" in resp.headers.get("Content-Type", "")
        raw = resp.read().decode()
        assert "data: " in raw
        assert "[DONE]" in raw


def test_proxy_ollama_chat_non_streaming(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    fake_response = CompletionResponse(
        content="Ollama format reply",
        provider="zai",
        model="glm-5.3",
        usage={"input_tokens": 7, "output_tokens": 4},
        finish_reason="stop",
    )
    monkeypatch.setattr(proxy, "_complete_model_direct", lambda *args, **kwargs: fake_response)

    payload = {
        "model": "glm-5.3",
        "messages": [{"role": "user", "content": "test"}],
        "stream": False,
    }
    headers = {"X-Ticket": "ticket-101"}
    status, body, resp_headers = _request("POST", f"{base_url}/api/chat", payload, headers=headers)
    assert status == 200
    assert body["done"] is True
    assert body["message"]["role"] == "assistant"
    assert body["message"]["content"] == "Ollama format reply"
    assert body["prompt_eval_count"] == 7
    assert body["eval_count"] == 4
    assert resp_headers.get("X-Subactor-Ticket") == "ticket-101"


def test_proxy_ollama_generate(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    fake_response = CompletionResponse(
        content="Generated completion",
        provider="zai",
        model="glm-5.3",
        usage={"input_tokens": 10, "output_tokens": 5},
        finish_reason="stop",
    )
    monkeypatch.setattr(proxy, "_complete_model_direct", lambda *args, **kwargs: fake_response)

    payload = {
        "model": "glm-5.3",
        "prompt": "Write a poem",
        "stream": False,
    }
    status, body, _ = _request("POST", f"{base_url}/api/generate", payload)
    assert status == 200
    assert body["done"] is True
    assert body["response"] == "Generated completion"


def test_proxy_route_notation_dispatch(proxy_server, monkeypatch):
    base_url, _ = proxy_server

    fake_response = CompletionResponse(
        content="Koru queue plan ready",
        provider="zai",
        model="glm-5.3",
        usage={"input_tokens": 20, "output_tokens": 10},
        finish_reason="stop",
    )
    called = []
    def fake_complete(app, func, messages, **kwargs):
        called.append((app, func))
        return fake_response

    monkeypatch.setattr(proxy, "complete", fake_complete)

    payload = {
        "model": "koru-agent/queue-executor@ticket-042",
        "messages": [{"role": "user", "content": "Execute queue"}],
        "stream": False,
    }
    status, body, headers = _request("POST", f"{base_url}/v1/chat/completions", payload)
    assert status == 200
    assert called == [("koru-agent", "queue-executor")]
    assert body["choices"][0]["message"]["content"] == "Koru queue plan ready"
    assert headers.get("X-Subactor-Ticket") == "ticket-042"


def test_proxy_rejects_non_local_host(proxy_server):
    base_url, _ = proxy_server
    status, body, _ = _request("GET", f"{base_url}/health", headers={"Host": "evil.external.com"})
    assert status == 421
    assert body["error"]["code"] == "PROXY-001"
