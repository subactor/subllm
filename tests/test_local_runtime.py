import json
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest

from subllm import InvalidPolicyError, complete, configured_routes, load_policy_config
from subllm.local_runtime import PROVIDER, local_base_url, main, render_profiles, write_profiles


@pytest.mark.parametrize("url", ["http://127.0.0.1:11435", "http://localhost:11435/v1/", "http://[::1]:11435"])
def test_loopback_url(url):
    assert local_base_url(url).endswith("/v1")


@pytest.mark.parametrize("url", ["http://192.168.188.170:11434", "http://0.0.0.0:11434", "https://8.8.8.8",
    "https://example.com", "http://minis:11434", "ftp://localhost", "http://u:p@localhost",
    "http://localhost?secret=x", "http://localhost/#x", "http://localhost/api/chat", "http://localhost:0",
    "http://localhost:65536"])
def test_invalid_endpoint(url):
    with pytest.raises(ValueError):
        local_base_url(url)


def test_https_private_endpoint():
    assert local_base_url("https://192.168.188.170:11434") == "https://192.168.188.170:11434/v1"


def test_profiles_disable_every_builtin_and_resolve_exact_route(tmp_path):
    env = write_profiles(tmp_path / "profile", base_url="http://127.0.0.1:11435", model="gemma4:12b")
    env.update({"ZAI_API_KEY": "must-not-route", "OPENROUTER_API_KEY": "must-not-route"})
    policy = load_policy_config(environ=env)
    assert all(not provider.enabled for provider in policy.providers.values())
    assert policy.execution.attempt_timeout_seconds == 300
    assert policy.execution.max_attempts == 1
    routes = configured_routes("koru-agent", "queue-executor", environ=env)
    assert [(r.provider, r.wire_model, r.api_base) for r in routes] == [
        (PROVIDER, "gemma4:12b", "http://127.0.0.1:11435/v1")]
    with pytest.raises(InvalidPolicyError, match="no enabled candidate"):
        configured_routes("validator-agent", "direct-pr-review", environ=env)


def test_matching_opencode_and_policy():
    profiles = render_profiles(base_url="http://localhost:11435/", model="gpt-oss:20b")
    toml = tomllib.loads(profiles["subllm.toml"])
    config = json.loads(profiles["opencode.json"])
    provider = config["provider"][PROVIDER]
    assert config["enabled_providers"] == [PROVIDER]
    assert config["model"] == config["small_model"] == PROVIDER + "/gpt-oss:20b"
    assert provider["options"]["baseURL"] == toml["custom_providers"][PROVIDER]["api_base"]
    assert provider["models"]["gpt-oss:20b"]["tool_call"] is True
    assert provider["models"]["gpt-oss:20b"]["limit"] == {"context": 16384, "output": 2048}
    assert "permission" not in config  # Ticket controller owns allowed effects.


@pytest.mark.parametrize("options", [{"model": "gpt-oss:20b-cloud"}, {"model": "bad\nmodel"},
    {"context": True}, {"context": 4095}, {"output_tokens": 16384}, {"timeout_seconds": 12},
    {"steps": 0}, {"routes": ()}, {"routes": ("all",)},
    {"routes": ("unknown/completion",)},
    {"routes": ("koru-agent/queue-executor", "koru-agent/queue-executor")}])
def test_bad_options(options):
    with pytest.raises(ValueError):
        render_profiles(**{"base_url": "http://localhost:11435", "model": "gemma4:12b", **options})


def test_preserve_existing_profile(tmp_path):
    directory = tmp_path / "profile"
    directory.mkdir()
    (directory / "subllm.toml").write_text("existing")
    with pytest.raises(FileExistsError):
        write_profiles(directory, base_url="http://localhost:11435", model="gemma4:12b")
    assert (directory / "subllm.toml").read_text() == "existing"
    assert not (directory / "opencode.json").exists()


def test_cli(tmp_path, capsys):
    assert main(["--base-url", "http://localhost:11435", "--model", "gemma4:12b",
                 "--output-dir", str(tmp_path / "profile")]) == 0
    assert json.loads(capsys.readouterr().out)["SUBLLM_POLICY_FILE"].endswith("/profile/subllm.toml")


def test_explicit_policy_reaches_real_worker_without_global_mutation(tmp_path, monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            payload = json.dumps({"choices": [{"message": {"content": "LOCAL_OK"},
                                  "finish_reason": "stop"}], "usage": {"total_tokens": 4}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.delenv("SUBLLM_POLICY_FILE", raising=False)
    stale = tmp_path / "stale-release" / "subllm"
    stale.mkdir(parents=True)
    (stale / "__init__.py").write_text("")
    (stale / "openai_worker.py").write_text("raise SystemExit(99)\n")
    monkeypatch.setenv("PYTHONPATH", str(stale.parent))
    env = write_profiles(tmp_path / "profile", base_url=f"http://127.0.0.1:{server.server_port}",
                         model="gemma4:12b")
    env["SUBLLM_HEALTH_STATE_FILE"] = str(tmp_path / "health.json")
    try:
        result = complete("koru-agent", "queue-executor", [{"role": "user", "content": "check"}],
                          timeout_seconds=10, environ=env)
        assert (result.provider, result.model, result.content) == (PROVIDER, "gemma4:12b", "LOCAL_OK")
        assert len(requests) == 1
        assert requests[0]["model"] == "gemma4:12b"
        import os
        assert "SUBLLM_POLICY_FILE" not in os.environ
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
