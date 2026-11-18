"""SUB-07: shared Ollama liveness state with a TTL; a slow probe means busy, not dead."""
from __future__ import annotations

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import subllm.proxy as proxy


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(proxy, "_LIVENESS", {})
    monkeypatch.setattr(proxy, "_LIVENESS_LOCKS", {})


def _upstream(delay: float = 0.0):
    hits = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            hits.append(self.path)
            time.sleep(delay)
            try:
                self.send_response(200)
                self.send_header("Content-Length", "13")
                self.end_headers()
                self.wfile.write(b'{"models":[]}')
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}", hits


def test_one_probe_per_ttl_regardless_of_request_count():
    server, url, hits = _upstream()
    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            states = list(pool.map(lambda _: proxy.upstream_ollama_state(url), range(64)))
        assert set(states) == {"alive"} and len(hits) == 1
        assert proxy.is_upstream_ollama_alive(url) and len(hits) == 1
    finally:
        server.shutdown()
        server.server_close()


def test_cache_expires_after_ttl(monkeypatch):
    monkeypatch.setenv(proxy.UPSTREAM_LIVENESS_TTL_ENV, "0")
    server, url, hits = _upstream()
    try:
        proxy.upstream_ollama_state(url)
        proxy.upstream_ollama_state(url)
        assert len(hits) == 2
    finally:
        server.shutdown()
        server.server_close()


def test_slow_ollama_is_busy_and_still_counts_as_local():
    server, url, _ = _upstream(delay=1.0)
    try:
        assert proxy.upstream_ollama_state(url, timeout=0.2) == "busy"
        assert proxy.is_upstream_ollama_alive(url, 0.2) is True
    finally:
        server.shutdown()
        server.server_close()


def test_refused_connection_is_dead():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    assert proxy.upstream_ollama_state(f"http://127.0.0.1:{port}") == "dead"
    assert proxy.is_upstream_ollama_alive(f"http://127.0.0.1:{port}") is False


@pytest.mark.parametrize(("raw", "expected"), [("5", 5.0), ("nan", 2.0), ("-1", 2.0), ("x", 2.0), ("120", 2.0)])
def test_ttl_setting_is_bounded(monkeypatch, raw, expected):
    monkeypatch.setenv(proxy.UPSTREAM_LIVENESS_TTL_ENV, raw)
    assert proxy._liveness_ttl() == expected


def test_fresh_probe_bypasses_and_refreshes_the_cache():
    server, url, hits = _upstream()
    try:
        proxy.upstream_ollama_state(url)
        assert proxy.upstream_ollama_state(url, fresh=True) == "alive"
        assert len(hits) == 2
        proxy.upstream_ollama_state(url)
        assert len(hits) == 2
    finally:
        server.shutdown()
        server.server_close()
