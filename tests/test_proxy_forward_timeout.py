"""SUB-05: raw Ollama forwards honour the request timeout (1-900 s) instead of a fixed 120 s."""
from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import subllm.proxy as proxy
from subllm import make_proxy_server

LOCAL = {"model": "unregistered-local:1b", "messages": [{"role": "user", "content": "x"}], "stream": False}


def _slow_upstream(delay: float):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            time.sleep(delay)
            body = json.dumps({"model": LOCAL["model"], "message": {"role": "assistant", "content": "ok"},
                               "done": True}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _proxy(monkeypatch, upstream: str):
    monkeypatch.setattr(proxy, "is_upstream_ollama_alive", lambda *a, **k: True)
    monkeypatch.setattr(proxy.adaptive, "policy", lambda *a, **kw: None)
    server = make_proxy_server("127.0.0.1", 0, ollama_upstream=upstream)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _post(server, path: str, payload: dict) -> tuple[int, dict]:
    url = f"http://127.0.0.1:{server.server_address[1]}{path}"
    req = Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read())


@pytest.mark.parametrize(("payload", "expected"), [
    (None, 120.0), ({}, 120.0), ({"timeout": 300}, 300.0), ({"timeout": 0.2}, 1.0), ({"timeout": 5000}, 900.0),
    ({"timeout": True}, 120.0), ({"timeout": "300"}, 120.0), ({"timeout": float("nan")}, 120.0),
    ({"timeout": -5}, 120.0), ([1, 2], 120.0),
])
def test_forward_timeout_comes_from_request_within_bounds(payload, expected):
    assert proxy.upstream_forward_timeout(payload) == expected


def test_long_request_timeout_reaches_the_upstream_call(monkeypatch):
    seen = []

    class _Resp:
        status = 200
        headers = {"Content-Type": "application/json"}

        def read(self):
            return b'{"done": true}'

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(proxy, "urlopen", lambda req, timeout: seen.append(timeout) or _Resp())
    server = _proxy(monkeypatch, "http://127.0.0.1:9")
    try:
        status, _ = _post(server, "/api/chat", {**LOCAL, "timeout": 300})
        assert status == 200 and seen == [300.0]
    finally:
        server.shutdown()
        server.server_close()


def test_slow_upstream_gives_504_and_a_longer_timeout_succeeds(monkeypatch):
    upstream = _slow_upstream(1.5)
    server = _proxy(monkeypatch, f"http://127.0.0.1:{upstream.server_address[1]}")
    try:
        status, body = _post(server, "/api/chat", {**LOCAL, "timeout": 1})
        assert status == 504 and body["error"]["code"] == "UPSTREAM_TIMEOUT"
        status, body = _post(server, "/api/chat", {**LOCAL, "timeout": 5})
        assert status == 200 and body["message"]["content"] == "ok"
    finally:
        for s in (server, upstream):
            s.shutdown()
            s.server_close()


def test_unreachable_upstream_stays_502(monkeypatch):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = _proxy(monkeypatch, f"http://127.0.0.1:{port}")
    try:
        status, body = _post(server, "/api/chat", {**LOCAL, "timeout": 5})
        assert status == 502 and body["error"]["code"] == "UPSTREAM_UNAVAILABLE"
    finally:
        server.shutdown()
        server.server_close()
