"""Loopback transport faults, with ephemeral TLS and no provider credentials."""
from __future__ import annotations

import json
import shutil
import ssl
import subprocess
import threading
import time
import urllib.request
from contextlib import contextmanager
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from urllib.error import HTTPError

import pytest

from subllm import CompletionError, native_http, openai_worker


@pytest.fixture(scope="module")
def tls_files(tmp_path_factory):
    executable = shutil.which("openssl")
    if executable is None:
        pytest.skip("Loopback TLS fixture requires openssl")
    folder = tmp_path_factory.mktemp("transport-tls")
    cert, key = folder / "certificate.pem", folder / "key.pem"
    subprocess.run([
        executable, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=localhost", "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1",
        "-keyout", str(key), "-out", str(cert),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    key.chmod(0o600)
    return cert, key


@pytest.fixture
def trusted_loopback(monkeypatch, tls_files):
    cert, _ = tls_files
    context = ssl.create_default_context(cafile=str(cert))
    factory = urllib.request.build_opener
    monkeypatch.setattr(urllib.request, "build_opener", lambda *handlers: factory(
        *handlers, urllib.request.HTTPSHandler(context=context)))
    monkeypatch.setattr(urllib.request, "_opener", None)
    for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NO_PROXY", "")
    monkeypatch.setenv("no_proxy", "")


@contextmanager
def serve(tls_files=None, *, payload=b"{}", status=200, location=None, pause=0, chunked=False):
    observed = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            observed.append(self.command)
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            self.send_response(status)
            if location:
                self.send_header("Location", location)
            self.send_header("Transfer-Encoding" if chunked else "Content-Length",
                             "chunked" if chunked else str(len(payload)))
            self.end_headers()
            if pause:
                time.sleep(pause)
            try:
                if chunked:
                    self.wfile.write(f"{len(payload):x}\r\n".encode() + payload + b"\r\n0\r\n\r\n")
                else:
                    self.wfile.write(payload)
            except OSError:
                pass  # The timeout/size-limit client may have closed its socket.

        do_GET = do_POST
        do_CONNECT = do_POST

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls_files:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*(str(p) for p in tls_files))
        server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"{'https' if tls_files else 'http'}://127.0.0.1:{server.server_port}", observed
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def source(base):
    return {"schema": "subllm.openai-worker-request/v1", "provider": "zai",
            "wire_model": "glm-5.3", "api_base": base, "api_key": "placeholder-transport-fixture",
            "messages": [{"role": "user", "content": "fixture"}], "model_parameters": {},
            "request_fields": {}, "extra_headers": {}, "response_format": None}


def invoke(transport, base, timeout=1):
    if transport == "worker":
        return openai_worker._execute({**source(base), "timeout_seconds": timeout})
    try:
        native_http.post_json(base + "/native", {}, {}, timeout)
    except native_http.NativeHTTPError as error:
        return {"outcome": error.outcome}
    return {"status": "SUCCESS"}


@pytest.mark.parametrize("transport", ["worker", "native"])
@pytest.mark.parametrize("status", [302, 307, 308])
def test_redirect_cannot_contact_a_second_server(transport, status, tls_files, trusted_loopback):
    with serve() as (other, redirected), serve(tls_files, status=status, location=other) as (base, first):
        result = invoke(transport, base)
    assert first == ["POST"]
    assert redirected == []
    assert result["outcome"] == f"http_{status}"


@pytest.mark.parametrize("transport", ["worker", "native"])
def test_ambient_proxy_is_not_contacted(transport, tls_files, trusted_loopback, monkeypatch):
    payload = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    with serve() as (proxy, proxied), serve(tls_files, payload=payload) as (base, direct):
        for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(name, proxy)
        result = invoke(transport, base)
    assert proxied == []
    assert direct == ["POST"]
    assert result["status"] == "SUCCESS"


@pytest.mark.parametrize("transport", ["worker", "native"])
@pytest.mark.parametrize("chunked", [False, True])
def test_oversized_body_is_rejected_before_json_parsing(
    transport, chunked, tls_files, trusted_loopback, monkeypatch,
):
    monkeypatch.setattr(openai_worker, "MAX_OPENAI_RESPONSE_BYTES", 128)
    monkeypatch.setattr(native_http, "MAX_RESPONSE_BYTES", 128)
    # Complete valid JSON must still fail when the byte limit has been exceeded.
    payload = json.dumps({"choices": [{"message": {"content": "x" * 300}}]}).encode()
    with serve(tls_files, payload=payload, chunked=chunked) as (base, requests):
        result = invoke(transport, base)
    assert result["outcome"] == "invalid_response"
    assert requests == ["POST"]


@pytest.mark.parametrize("transport", ["worker", "native"])
def test_stalled_body_hits_finite_timeout(transport, tls_files, trusted_loopback):
    with serve(tls_files, payload=b"{}", pause=0.3, chunked=True) as (base, requests):
        result = invoke(transport, base, timeout=0.05)
    assert result["outcome"] == "timeout"
    assert requests == ["POST"]


@pytest.mark.parametrize("transport", ["worker", "native"])
@pytest.mark.parametrize("payload", [b"not-json", b"[" * 3000 + b"0" + b"]" * 3000], ids=["malformed", "deep"])
def test_malformed_or_deep_response_is_a_controlled_error(transport, payload, tls_files, trusted_loopback):
    with serve(tls_files, payload=payload) as (base, requests):
        result = invoke(transport, base)
    assert result["outcome"] == "invalid_response"
    assert requests == ["POST"]
    assert "placeholder-transport-fixture" not in repr(result)


def test_worker_read_is_bounded_before_buffering(monkeypatch):
    class GuardedResponse(BytesIO):
        def read(self, size=-1):
            assert 0 < size <= openai_worker.MAX_OPENAI_RESPONSE_BYTES + 1
            return super().read(size)
    monkeypatch.setattr(openai_worker, "urlopen", lambda *_args, **_kwargs: GuardedResponse(b"{}"))
    assert openai_worker._execute(source("https://fixture.invalid"))["outcome"] == "invalid_response"


def test_worker_never_retries_a_timeout_typeerror(monkeypatch):
    calls = []
    def fail(*_args, **_kwargs):
        calls.append(1)
        raise TypeError("timeout placeholder-transport-fixture from an already-started request")
    monkeypatch.setattr(openai_worker, "urlopen", fail)
    result = openai_worker._execute(source("https://fixture.invalid"))
    assert result["outcome"] == "transport_error"
    assert "placeholder-transport-fixture" not in repr(result)
    assert calls == [1]


@pytest.mark.parametrize("timeout", [float("inf"), float("nan"), 0, -1, True,
                                     pytest.param(10 ** 1000, id="overflow")])
def test_nonfinite_timeouts_fail_without_network(timeout, monkeypatch):
    calls = []
    monkeypatch.setattr(urllib.request, "build_opener", lambda *_args: calls.append(1))
    with pytest.raises(ValueError):
        native_http.open_request(urllib.request.Request("https://fixture.invalid"), timeout=timeout)
    with pytest.raises(native_http.NativeHTTPError):
        native_http.post_json("https://fixture.invalid", {}, {}, timeout)
    worker_source = {**source("https://fixture.invalid"), "timeout_seconds": timeout}
    with pytest.raises(CompletionError, match="finite positive"):
        openai_worker._request(worker_source)
    assert calls == []


def test_deep_http_error_cannot_escape_or_repeat_transport(monkeypatch):
    calls = []
    def reject(*_args, **_kwargs):
        calls.append(1)
        raise HTTPError("https://fixture.invalid", 429, "fixture", {}, BytesIO(b"[" * 3000 + b"]" * 3000))
    monkeypatch.setattr(openai_worker, "urlopen", reject)
    result = openai_worker._execute(source("https://fixture.invalid"))
    assert result["outcome"] == "http_429"
    assert calls == [1]


@pytest.mark.parametrize("depth", [64, 65])
def test_json_nesting_has_an_explicit_portable_boundary(depth):
    payload = b"[" * depth + b"0" + b"]" * depth
    if depth == 64:
        assert isinstance(native_http.decode_response_json(payload), list)
    else:
        with pytest.raises(ValueError, match="nesting"):
            native_http.decode_response_json(payload)


def test_empty_credential_does_not_corrupt_captured_exchange(monkeypatch):
    payload = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode()
    monkeypatch.setattr(openai_worker, "urlopen", lambda *_args, **_kwargs: BytesIO(payload))
    request = {**source("https://fixture.invalid"), "api_key": "", "capture_exchange": True}
    result = openai_worker._execute(request)
    assert result["exchange"]["request"]["messages"] == request["messages"]
    assert result["content"] == "ok"


def test_redirect_records_one_native_attempt_and_one_usage_entry(
    monkeypatch, tmp_path, tls_files, trusted_loopback,
):
    from subllm import client_routes, client_workers, interaction_store, resolve
    from subllm.usage import query_usage
    monkeypatch.setenv("SUBLLM_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setattr(interaction_store, "_DEFAULT_STORE", None)
    route = resolve("onedev-agent", "code-edit", provider="zai",
                    environ={"SUBLLM_PROVIDER_ORDER": "zai", "ZAI_API_KEY": "id.secret"})
    monkeypatch.setattr(client_workers, "_run_openai_worker",
                        lambda request, **_kwargs: openai_worker._execute(request))
    begins = []
    original = client_routes.begin_attempt
    def begin(*args, **kwargs):
        begins.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(client_routes, "begin_attempt", begin)
    with (
        serve() as (other, redirected),
        serve(tls_files, status=302, location=other) as (base, first),
        pytest.raises(CompletionError),
    ):
        client_routes._complete_route(replace(route, api_base=base), [{"role": "user", "content": "fixture"}],
                                      timeout_seconds=1, request_id="fixture-one-attempt",
                                      response_format=None, cwd=tmp_path)
    assert first == ["POST"] and redirected == [] and begins == [1]
    summary = query_usage({})["summary"]
    assert summary["attempts"] == 1 and summary["requests"] == 1
