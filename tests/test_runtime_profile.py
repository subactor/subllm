"""Operator configuration must not leak credentials or migrate in-flight work."""

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from subllm.runtime_profile import (
    GatewayClient,
    GatewayError,
    ProfileError,
    ProfileStore,
    default_profile,
    public_profile,
    validate_profile,
)


def configured(url="http://127.0.0.1:11437"):
    profile = default_profile()
    profile["enabled"] = True
    profile["gateway"] = {"url": url, "api_key": "test-key"}
    return profile


def test_atomic_profile_revision_and_public_credential_handling(tmp_path):
    path = tmp_path / "private" / "ai-runtime.json"
    store = ProfileStore(path)
    saved = store.save(configured(), expected_revision=0)
    assert saved["revision"] == 1
    assert saved["gateway"]["keySet"] is True
    assert "test-key" not in json.dumps(saved)
    assert store.load()["gateway"]["api_key"] == "test-key"
    if os.name != "nt":
        assert path.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ProfileError, match="revision conflict"):
        store.save(configured(), expected_revision=0)
    assert store.load()["revision"] == 1


def test_new_gateway_never_inherits_credentials(tmp_path):
    store = ProfileStore(tmp_path / "ai-runtime.json")
    public = store.save(configured(), expected_revision=0)
    public["roles"]["llm"]["model"] = "another-model"
    public = store.save(public, expected_revision=1)
    assert store.load()["gateway"]["api_key"] == "test-key"
    public["gateway"]["url"] = "https://other-gateway.example"
    store.save(public, expected_revision=2)
    assert store.load()["gateway"]["api_key"] == ""


def test_concurrent_writers_cannot_lose_an_update(tmp_path):
    path = tmp_path / "ai-runtime.json"
    barrier = threading.Barrier(2)
    results = []

    def writer(model):
        store = ProfileStore(path)
        candidate = store.load()
        candidate["roles"]["llm"]["model"] = model
        barrier.wait(timeout=5)
        try:
            store.save(candidate, expected_revision=0)
            results.append("saved")
        except ProfileError:
            results.append("conflict")

    workers = [threading.Thread(target=writer, args=(name,)) for name in ("one", "two")]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=5)
        assert not worker.is_alive()
    assert sorted(results) == ["conflict", "saved"]
    assert ProfileStore(path).load()["revision"] == 1


@pytest.mark.parametrize(
    "parameter,value",
    [
        ("temperature", float("nan")),
        ("max_tokens", True),
        ("top_p", 1.5),
        ("messages", []),
        ("api_key", "test-other-key"),
        ("unknown_option", 4),
    ],
)
def test_invalid_or_authority_parameters_are_rejected(parameter, value):
    profile = configured()
    profile["roles"]["llm"]["parameters"][parameter] = value
    with pytest.raises(ProfileError):
        validate_profile(profile)


@pytest.mark.parametrize(
    "url",
    [
        "https://user:example@gateway.example",
        "http://127.0.0.1:0",
        "https://gateway.example/another/path",
        "https://gateway.example/#fragment",
    ],
)
def test_invalid_gateway_origins_are_rejected(url):
    with pytest.raises(ProfileError):
        validate_profile(configured(url))


def test_existing_corrupt_profile_does_not_disable_routing_silently(tmp_path):
    path = tmp_path / "ai-runtime.json"
    path.write_text("{broken")
    path.chmod(0o600)
    with pytest.raises(ProfileError):
        ProfileStore(path).load()


def test_profile_symlink_cannot_redirect_private_configuration(tmp_path):
    original = tmp_path / "original.json"
    original.write_text(json.dumps(configured()))
    link = tmp_path / "ai-runtime.json"
    link.symlink_to(original)
    with pytest.raises(ProfileError, match="symlink"):
        ProfileStore(link)


@pytest.fixture
def gateway_servers():
    seen = []
    entered, release = threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append(
                {
                    "port": self.server.server_port,
                    "path": self.path,
                    "payload": payload,
                    "auth": self.headers.get("Authorization"),
                }
            )
            if self.server.block:
                entered.set()
                if not release.wait(timeout=5):
                    self.send_error(504)
                    return
            body = json.dumps({"model": payload["model"], "ok": True}).encode()
            self.send_response(self.server.result_status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    servers = [ThreadingHTTPServer(("127.0.0.1", 0), Handler) for _ in range(2)]
    for server in servers:
        server.block, server.result_status = False, 200
        threading.Thread(target=server.serve_forever, daemon=True).start()
    yield servers, seen, entered, release
    release.set()
    for server in servers:
        server.shutdown()
        server.server_close()


def test_inflight_request_keeps_profile_and_next_request_uses_new_revision(tmp_path, gateway_servers):
    servers, seen, entered, release = gateway_servers
    servers[0].block = True
    store = ProfileStore(tmp_path / "ai-runtime.json")
    first = configured(f"http://127.0.0.1:{servers[0].server_port}")
    first["roles"]["llm"]["parameters"] = {"temperature": 0.3, "top_p": 0.85, "max_tokens": 123}
    store.save(first, expected_revision=0)
    client = GatewayClient(store.load())
    results = []
    worker = threading.Thread(
        target=lambda: results.append(client.infer("llm", {"messages": [{"role": "user", "content": "hello"}]}))
    )
    worker.start()
    try:
        assert entered.wait(timeout=5)
        next_profile = public_profile(store.load())
        next_profile["gateway"]["url"] = f"http://127.0.0.1:{servers[1].server_port}"
        next_profile["roles"]["llm"]["model"] = "next-model"
        store.save(next_profile, expected_revision=1)
    finally:
        release.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    new_result = GatewayClient(store.load()).infer("llm", {"messages": []})
    assert results[0]["model"] == first["roles"]["llm"]["model"]
    assert new_result["model"] == "next-model"
    assert seen[0]["port"] == servers[0].server_port
    assert seen[0]["payload"]["top_p"] == 0.85
    assert seen[0]["payload"]["max_tokens"] == 123
    assert seen[0]["auth"] == "Bearer test-key"
    assert seen[1]["port"] == servers[1].server_port
    assert seen[1]["auth"] is None


def test_gateway_failure_does_not_attempt_another_provider(gateway_servers):
    servers, seen, _entered, _release = gateway_servers
    servers[0].result_status = 503
    client = GatewayClient(configured(f"http://127.0.0.1:{servers[0].server_port}"))
    with pytest.raises(GatewayError) as error:
        client.infer("stt", {"audio_base64": "UklGRg=="})
    assert error.value.status == 503
    assert len(seen) == 1
    assert seen[0]["path"] == "/v1/speech/transcribe"


def test_disabled_profile_cannot_make_an_inference_request():
    with pytest.raises(ProfileError, match="disabled"):
        GatewayClient(default_profile())


@pytest.mark.parametrize("ceiling", [64, "64"])
def test_sampling_controls_reach_canonical_invocation_without_raising_operator_cap(monkeypatch, tmp_path, ceiling):
    from subllm import client_routes
    from subllm.client_types import CompletionResponse
    from subllm.runtime_profile import request_parameter_scope
    from subllm.types import ResolvedRoute

    route = ResolvedRoute(
        application="test",
        application_name="test",
        application_url="",
        function="chat",
        provider="openai",
        model="test-model",
        priority=1,
        api_base="http://127.0.0.1:9/v1",
        api_key_env="TEST_KEY",
        litellm_model="openai/test-model",
        wire_model="test-model",
        extra_headers={},
        transport="openai-compatible",
        api_key="test-key",
        model_parameters={"max_tokens": ceiling},
    )
    seen = []

    def invoke(selected, *_args, **_kwargs):
        seen.append(selected)
        return CompletionResponse("ok", "openai", "test-model", {"completion_tokens": 1})

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    with request_parameter_scope({"temperature": 0.25, "top_p": 0.9, "max_tokens": 1000}):
        result = client_routes._complete_route(
            route,
            [{"role": "user", "content": "hello"}],
            timeout_seconds=5,
            request_id="test-parameters",
            response_format=None,
            cwd=tmp_path,
        )
    assert result.content == "ok"
    assert seen[0].model_parameters["temperature"] == 0.25
    assert seen[0].model_parameters["top_p"] == 0.9
    assert int(seen[0].model_parameters["max_tokens"]) == 64
    assert route.model_parameters == {"max_tokens": ceiling}


def test_request_parameter_context_resets_and_rejects_unsupported_native_controls():
    from subllm.runtime_profile import request_parameter_scope, request_parameters_active

    assert not request_parameters_active()
    with request_parameter_scope({"temperature": 0.2}):
        assert request_parameters_active()
    assert not request_parameters_active()
    with pytest.raises(ProfileError, match="Ollama API"), request_parameter_scope({"top_k": 20}):
        pytest.fail("Unsupported parameters must fail before provider dispatch")
