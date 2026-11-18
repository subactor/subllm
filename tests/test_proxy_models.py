"""SUB-06: real local tags and metadata in /v1/models, /api/tags and /api/show."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen

import pytest

import subllm.proxy as proxy
from subllm import make_proxy_server

UPSTREAM_TAGS = [
    {"name": "qwen2.5-coder:7b", "model": "qwen2.5-coder:7b", "size": 4683087332, "digest": "sha256:aaa",
     "modified_at": "2026-11-01T10:00:00Z",
     "details": {"format": "gguf", "family": "qwen2", "families": ["qwen2"], "parameter_size": "7.6B",
                 "quantization_level": "Q4_K_M"}},
    {"name": "qwen2.5-coder:3b", "model": "qwen2.5-coder:3b", "size": 1929912432, "digest": "sha256:bbb",
     "modified_at": "2026-11-02T10:00:00Z",
     "details": {"format": "gguf", "family": "qwen2", "families": ["qwen2"], "parameter_size": "3.1B",
                 "quantization_level": "Q8_0"}},
    {"name": "d1:3b", "model": "d1:3b", "size": 2019393189, "digest": "sha256:ccc",
     "modified_at": "2026-11-03T10:00:00Z",
     "details": {"format": "gguf", "family": "llama", "parameter_size": "3.2B", "quantization_level": "Q4_K_M"}},
]
SHOW = {"modelfile": "FROM /models/qwen2.5-coder-7b.gguf", "details": {"parameter_size": "7.6B",
                                                                      "quantization_level": "Q4_K_M"}}


@pytest.fixture
def servers(monkeypatch):
    class Upstream(BaseHTTPRequestHandler):
        shows: list = []

        def _send(self, doc):
            body = json.dumps(doc).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            self._send({"models": UPSTREAM_TAGS})

        def do_POST(self):  # noqa: N802
            Upstream.shows.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self._send(SHOW)

        def log_message(self, *args):
            pass

    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    monkeypatch.setattr(proxy, "is_upstream_ollama_alive", lambda *a, **k: True)
    server = make_proxy_server("127.0.0.1", 0, ollama_upstream=f"http://127.0.0.1:{upstream.server_address[1]}")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server, Upstream.shows
    for s in (server, upstream):
        s.shutdown()
        s.server_close()


def _call(server, method, path, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = Request(f"http://127.0.0.1:{server.server_address[1]}{path}", data=data, method=method,
                  headers={"Content-Type": "application/json", "Cache-Control": "no-cache"})
    with urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def test_upstream_tags_of_a_catalog_family_stay_visible(servers):
    server, _ = servers
    ids = [m["id"] for m in _call(server, "GET", "/v1/models")["data"]]
    assert "qwen2.5-coder" in ids and "qwen2.5-coder:7b" in ids and "qwen2.5-coder:3b" in ids and "d1:3b" in ids
    assert len(ids) == len(set(ids))


def test_api_tags_reports_real_local_metadata_and_no_invented_remote_size(servers):
    server, _ = servers
    tags = {m["name"]: m for m in _call(server, "GET", "/api/tags")["models"]}
    local = tags["qwen2.5-coder:3b"]
    assert local["size"] == 1929912432 and local["digest"] == "sha256:bbb"
    assert local["modified_at"] == "2026-11-02T10:00:00Z"
    assert local["details"]["parameter_size"] == "3.1B" and local["details"]["quantization_level"] == "Q8_0"
    remote = tags["qwen2.5-coder:latest"]
    assert remote["size"] == 0 and remote["details"]["quantization_level"] == "remote"
    assert remote["details"]["parameter_size"] != "32B"
    assert not [m for m in tags.values() if m["size"] == 32212254720]


def test_api_show_forwards_local_tags_and_describes_routed_models_honestly(servers):
    server, shows = servers
    assert _call(server, "POST", "/api/show", {"model": "qwen2.5-coder:7b"}) == SHOW
    assert shows == [{"model": "qwen2.5-coder:7b"}]
    routed = _call(server, "POST", "/api/show", {"model": "qwen2.5-coder"})
    assert routed["details"]["parameter_size"] == "unknown" and routed["details"]["quantization_level"] == "remote"
    assert len(shows) == 1


def test_identical_tag_is_shadowed_by_the_catalog():
    models = proxy.list_proxy_models(include_upstream=False)
    catalog_names = {m["name"] for m in models}
    assert "qwen2.5-coder:latest" in catalog_names
    assert all(m["parameter_size"] == "unknown" for m in models)


def test_api_show_forwards_a_local_tag_even_when_the_tag_list_is_unavailable(servers, monkeypatch):
    server, shows = servers
    monkeypatch.setattr(proxy, "get_upstream_ollama_models", lambda *a, **k: [])  # /api/tags timed out
    assert _call(server, "POST", "/api/show", {"model": "qwen2.5-coder:7b"}) == SHOW
    routed = _call(server, "POST", "/api/show", {"model": "qwen2.5-coder:latest"})
    assert routed["details"]["quantization_level"] == "remote" and len(shows) == 1
