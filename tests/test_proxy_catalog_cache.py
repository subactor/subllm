from __future__ import annotations

import io
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib import request as urllib_request
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from subllm import proxy

MODELS = [{"name": "catalog-fixture:latest"}]


class Response:
    status = 200

    def __init__(self, body=None, headers=None):
        self.body = json.dumps({"models": MODELS}).encode() if body is None else body
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self):
        return self.body


@pytest.fixture(autouse=True)
def private_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("SUBACTOR_PROCACHE_PATH", str(tmp_path / "catalog.sqlite3"))
    monkeypatch.setenv("SUBLLM_MODEL_CATALOG_CACHE_TTL", "15")
    original_reader = proxy._catalog_reader
    original_reader.cache_clear()
    yield tmp_path / "catalog.sqlite3"
    original_reader.cache_clear()


@pytest.fixture
def transport(monkeypatch):
    calls = []

    def request(req, *, timeout):
        calls.append((req.full_url, timeout))
        return Response()

    monkeypatch.setattr(proxy, "urlopen", request)
    return calls


def test_repeated_catalog_uses_actual_canonical_adapter(transport):
    assert proxy.get_upstream_ollama_models() == MODELS
    assert proxy.get_upstream_ollama_models() == MODELS
    assert len(transport) == 1
    reader, _ = proxy._optional_catalog_reader()
    assert type(reader).__module__ == "procache.http"


def test_health_stays_live_even_when_catalog_is_cached(transport):
    proxy.get_upstream_ollama_models()
    assert proxy.is_upstream_ollama_alive()
    assert proxy.is_upstream_ollama_alive()
    assert proxy.get_upstream_ollama_models() == MODELS
    assert len(transport) == 3


def test_explicit_freshness_bypasses_existing_catalog(transport):
    proxy.get_upstream_ollama_models()
    for _ in range(2):
        assert proxy.get_upstream_ollama_models(fresh=True) == MODELS
    assert len(transport) == 3


def test_catalog_expires_without_waiting_for_real_time(transport):
    reader, _ = proxy._optional_catalog_reader()
    clock = [100.0]
    reader.cache._clock = lambda: clock[0]
    assert proxy.get_upstream_ollama_models() == MODELS
    clock[0] += 14
    assert proxy.get_upstream_ollama_models() == MODELS
    assert len(transport) == 1
    clock[0] += 2
    assert proxy.get_upstream_ollama_models() == MODELS
    assert len(transport) == 2


def test_distinct_upstreams_do_not_share_catalog(transport):
    for host in ("http://127.0.0.1:11434", "http://127.0.0.1:11435"):
        assert proxy.get_upstream_ollama_models(host) == MODELS
        assert proxy.get_upstream_ollama_models(host) == MODELS
    assert len(transport) == 2


@pytest.mark.parametrize("ttl", ["0", "-1", "nan", "inf", "3601", "invalid"])
def test_zero_or_invalid_ttl_keeps_live_reads(transport, monkeypatch, private_cache, ttl):
    monkeypatch.setenv("SUBLLM_MODEL_CATALOG_CACHE_TTL", ttl)
    assert proxy.get_upstream_ollama_models() == MODELS
    assert proxy.get_upstream_ollama_models() == MODELS
    assert len(transport) == 2 and not private_cache.exists()


def test_url_credentials_do_not_become_an_anonymous_cache_identity(transport, private_cache):
    url = "http://fixture-account:fixture-value@localhost:11434"
    assert proxy.get_upstream_ollama_models(url) == MODELS
    assert proxy.get_upstream_ollama_models(url) == MODELS
    assert len(transport) == 2 and not private_cache.exists()


@pytest.mark.parametrize("ambient", ["auth", "cookies", "tenant-header"])
def test_ambient_http_identity_is_unknown_and_bypasses_cache(transport, monkeypatch, private_cache, ambient):
    if ambient == "auth":
        opener = urllib_request.build_opener(urllib_request.HTTPBasicAuthHandler())
    elif ambient == "cookies":
        opener = urllib_request.build_opener(urllib_request.HTTPCookieProcessor())
    else:
        opener = urllib_request.build_opener()
        opener.addheaders.append(("X-Tenant", "fixture-tenant"))
    monkeypatch.setattr(urllib_request, "_opener", opener)
    assert proxy.get_upstream_ollama_models() == MODELS
    assert proxy.get_upstream_ollama_models() == MODELS
    assert len(transport) == 2 and not private_cache.exists()


def test_missing_optional_dependency_preserves_live_transport(transport, monkeypatch):
    def missing(*_):
        raise ImportError("cache extra not installed")

    monkeypatch.setattr(proxy, "_catalog_reader", missing)
    assert proxy.get_upstream_ollama_models() == MODELS
    assert proxy.get_upstream_ollama_models() == MODELS
    assert len(transport) == 2


def test_failure_before_transport_falls_back_exactly_once(transport, monkeypatch):
    reader, _ = proxy._optional_catalog_reader()

    def unavailable(*_):
        raise sqlite3.OperationalError("fixture unavailable")

    monkeypatch.setattr(reader.cache, "get", unavailable)
    assert proxy.get_upstream_ollama_models() == MODELS
    assert len(transport) == 1


def test_cache_write_failure_does_not_repeat_successful_transport(transport, monkeypatch):
    reader, _ = proxy._optional_catalog_reader()

    def unavailable(*_, **__):
        raise sqlite3.OperationalError("fixture unavailable")

    monkeypatch.setattr(reader.cache, "put", unavailable)
    assert proxy.get_upstream_ollama_models() == MODELS
    assert len(transport) == 1


@pytest.mark.parametrize("body", [b"invalid", b'[]', b'{"error":"denied"}',
                                  b'{"models":{}}', b'{"models":[null]}'])
def test_invalid_catalogs_are_not_stored(monkeypatch, body):
    calls = []

    def request(*_, **__):
        calls.append(1)
        return Response(body)

    monkeypatch.setattr(proxy, "urlopen", request)
    assert proxy.get_upstream_ollama_models() == []
    assert proxy.get_upstream_ollama_models() == []
    assert len(calls) == 2


def test_empty_valid_catalog_is_cached(monkeypatch):
    calls = []

    def request(*_, **__):
        calls.append(1)
        return Response(b'{"models":[]}')

    monkeypatch.setattr(proxy, "urlopen", request)
    assert proxy.get_upstream_ollama_models() == []
    assert proxy.get_upstream_ollama_models() == []
    assert len(calls) == 1


def test_server_no_store_is_honored(monkeypatch):
    calls = []

    def request(*_, **__):
        calls.append(1)
        return Response(headers={"Cache-Control": "no-store"})

    monkeypatch.setattr(proxy, "urlopen", request)
    assert proxy.get_upstream_ollama_models() == MODELS
    assert proxy.get_upstream_ollama_models() == MODELS
    assert len(calls) == 2


def test_rate_limit_uses_shared_cooldown_without_a_live_retry(monkeypatch):
    calls = []

    def limited(req, **_):
        calls.append(1)
        raise HTTPError(req.full_url, 429, "fixture limit", {"Retry-After": "60"}, io.BytesIO(b'{}'))

    monkeypatch.setattr(proxy, "urlopen", limited)
    assert proxy.get_upstream_ollama_models() == []
    assert proxy.get_upstream_ollama_models() == []
    assert len(calls) == 1


def test_concurrent_catalog_readers_share_one_transport(transport):
    start = threading.Barrier(6)

    def read(_):
        start.wait(timeout=5)
        return proxy.get_upstream_ollama_models()

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(read, range(6)))
    assert results == [MODELS] * 6
    assert len(transport) == 1


@pytest.mark.parametrize("endpoint", ["/api/tags", "/v1/models"])
@pytest.mark.parametrize("headers", [{"Cache-Control": "no-cache"}, {"Cache-Control": "no-store"},
                                     {"Cache-Control": 'max-age="00"'}, {"Pragma": "no-cache"}])
def test_http_catalog_freshness_headers_reach_upstream(transport, endpoint, headers):
    server = proxy.make_proxy_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}{endpoint}"
    try:
        for _ in range(2):
            with urlopen(url, timeout=5) as response:
                assert response.status == 200
        assert len(transport) == 1
        with urlopen(Request(url, headers=headers), timeout=5) as response:
            assert response.status == 200
        assert len(transport) == 2
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
