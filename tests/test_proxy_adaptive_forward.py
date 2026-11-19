"""AUT-011: installed local Ollama tags stay usable when an adaptive (cloud class) policy is active."""
from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import subllm.proxy as proxy

POLICY = {"classes": {"fast": ["gemini-3.8-flash"]}, "aliases": {"declared-local:1b": "fast"}}


@pytest.fixture
def server(monkeypatch):
    forwarded = []
    monkeypatch.setattr(proxy.adaptive, "policy", lambda *a, **k: POLICY)
    monkeypatch.setattr(proxy, "is_upstream_ollama_alive", lambda *a, **k: True)
    monkeypatch.setattr(proxy, "get_upstream_ollama_models",
                        lambda *a, **k: [{"name": "qwen2.5-coder:3b"}, {"name": "declared-local:1b"}])

    def fake_forward(self, method, path, payload):
        forwarded.append((path, payload.get("model"), payload.get("options")))
        self._json(200, {"model": payload.get("model"), "message": {"role": "assistant", "content": "{}"},
                         "done": True})

    monkeypatch.setattr(proxy.SubLLMProxyHandler, "_forward_upstream", fake_forward)
    srv = proxy.make_proxy_server("127.0.0.1", 0, ollama_upstream="http://127.0.0.1:1")
    import threading
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv, forwarded
    srv.shutdown()
    srv.server_close()


def _post(srv, path, payload):
    req = Request(f"http://127.0.0.1:{srv.server_address[1]}{path}", data=json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json", "X-Subactor-Application": "autonom",
                           "X-Subactor-Function": "bind"}, method="POST")
    try:
        with urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


def test_installed_local_tag_is_forwarded_with_native_options(server):
    srv, forwarded = server
    status, _ = _post(srv, "/api/chat", {"model": "qwen2.5-coder:3b", "stream": False, "format": "json",
                                         "options": {"num_ctx": 4096, "temperature": 0},
                                         "messages": [{"role": "user", "content": "x"}]})
    assert status == 200
    assert forwarded == [("/api/chat", "qwen2.5-coder:3b", {"num_ctx": 4096, "temperature": 0})]


def test_missing_local_tag_still_fails_as_unknown_under_adaptive_policy(server):
    srv, forwarded = server
    status, body = _post(srv, "/api/chat", {"model": "qwen2.5-coder:7b", "stream": False,
                                            "messages": [{"role": "user", "content": "x"}]})
    assert status >= 400 and forwarded == []
    assert "unknown model" in json.dumps(body)


def test_tag_declared_by_the_adaptive_policy_is_not_forwarded(server, monkeypatch):
    srv, forwarded = server
    monkeypatch.setattr(proxy.SubLLMProxyHandler, "_execute_model_or_route",
                        lambda self, *a, **k: (_ for _ in ()).throw(proxy.CompletionError("adaptive path")))
    _post(srv, "/api/chat", {"model": "declared-local:1b", "stream": False,
                             "messages": [{"role": "user", "content": "x"}]})
    assert forwarded == []


def test_without_adaptive_policy_behaviour_is_unchanged(server, monkeypatch):
    srv, forwarded = server
    monkeypatch.setattr(proxy.adaptive, "policy", lambda *a, **k: None)
    status, _ = _post(srv, "/api/chat", {"model": "not-installed:1b", "stream": False,
                                         "messages": [{"role": "user", "content": "x"}]})
    assert status == 200 and forwarded[-1][1] == "not-installed:1b"
