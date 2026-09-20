from __future__ import annotations

import os
from pathlib import Path

import pytest

from subllm import (
    CompletionError,
    InvalidPolicyError,
    configured_routes,
    load_policy_config,
    resolve,
)
from subllm.openai_worker import _request
from subllm.policy import (
    APPLICATIONS,
    MODELS,
    ORDERABLE_PROVIDER_IDS,
    PROVIDERS,
    clear_custom_providers,
)


def _base_policy_lines() -> list[str]:
    app_lines = []
    for app in APPLICATIONS.values():
        app_lines.extend([
            f"[applications.{app.id}]",
            f'name = "{app.title}"',
            f'url = "{app.url}"',
            "",
        ])
    return [
        "schema_version = 3",
        "",
        "[providers.zai]",
        "enabled = true",
        "priority = 0",
        'default_model = "glm-5.3"',
        "",
        "[providers.agy]",
        "enabled = true",
        "priority = 10",
        'default_model = "gemini-3.1-pro-high"',
        "",
        "[providers.codex-cli]",
        "enabled = false",
        "priority = 16",
        'default_model = "gpt-5.6-sol"',
        "",
        "[providers.agy-cli]",
        "enabled = false",
        "priority = 12",
        'default_model = "claude-sonnet-4-6"',
        "",
        "[providers.claude-cli]",
        "enabled = false",
        "priority = 17",
        'default_model = "claude-sonnet-5"',
        "",
        "[providers.codex]",
        "enabled = true",
        "priority = 15",
        'default_model = "gpt-5.6-sol"',
        "",
        "[providers.claude]",
        "enabled = true",
        "priority = 18",
        'default_model = "claude-opus-5"',
        "",
        "[providers.cursor]",
        "enabled = true",
        "priority = 20",
        'default_model = "gpt-5.6-sol"',
        "",
        "[providers.ollama]",
        "enabled = true",
        "priority = 25",
        'default_model = "qwen3-coder:30b"',
        "",
        "[providers.openrouter]",
        "enabled = true",
        "priority = 30",
        'default_model = "glm-5.3-flash"',
        "",
        *app_lines,
        "[execution]",
        "failover_enabled = true",
        "attempt_timeout_seconds = 12.0",
        "slow_response_seconds = 10.0",
        "cooldown_seconds = 60.0",
        "failure_threshold = 1",
        "max_attempts = 6",
    ]


@pytest.fixture(autouse=True)
def _reset_custom_catalog():
    yield
    clear_custom_providers()


def test_custom_provider_valid_loading(tmp_path: Path):
    lines = _base_policy_lines() + [
        "",
        "[custom_providers.vllm-local]",
        'api_base = "http://127.0.0.1:8000/v1"',
        'api_key_env = "VLLM_API_KEY"',
        'default_model = "meta-llama/Llama-3.3-70B-Instruct"',
        'models = ["meta-llama/Llama-3.3-70B-Instruct", "mistralai/Mistral-Small-24B-Instruct-2501"]',
        "priority = 40",
        "enabled = true",
        "",
        "[custom_providers.fast-remote]",
        'api_base = "https://llm.example.com/v1"',
        'default_model = "deepseek-ai/DeepSeek-V3"',
        "priority = 45",
    ]
    policy_file = tmp_path / "subllm.toml"
    policy_file.write_text("\n".join(lines))

    config = load_policy_config(cwd=tmp_path)
    assert "vllm-local" in config.custom_providers
    assert "fast-remote" in config.custom_providers

    vllm = config.custom_providers["vllm-local"]
    assert vllm.id == "vllm-local"
    assert vllm.api_base == "http://127.0.0.1:8000/v1"
    assert vllm.api_key_env == "VLLM_API_KEY"
    assert vllm.default_model == "meta-llama/Llama-3.3-70B-Instruct"
    assert "mistralai/Mistral-Small-24B-Instruct-2501" in vllm.models
    assert vllm.priority == 40
    assert vllm.enabled is True

    # Check dynamic registration in PROVIDERS and MODELS
    assert "vllm-local" in PROVIDERS
    assert PROVIDERS["vllm-local"].api_base == "http://127.0.0.1:8000/v1"
    assert PROVIDERS["vllm-local"].transport == "openai-compatible"

    assert "meta-llama/Llama-3.3-70B-Instruct" in MODELS
    model_spec = MODELS["meta-llama/Llama-3.3-70B-Instruct"]
    assert "vllm-local" in model_spec.providers
    assert model_spec.providers["vllm-local"].wire_model == "meta-llama/Llama-3.3-70B-Instruct"

    assert "vllm-local" in ORDERABLE_PROVIDER_IDS


def test_custom_provider_conflicts_with_builtin(tmp_path: Path):
    lines = _base_policy_lines() + [
        "",
        "[custom_providers.zai]",
        'api_base = "https://custom.z.ai/v1"',
    ]
    policy_file = tmp_path / "subllm.toml"
    policy_file.write_text("\n".join(lines))

    with pytest.raises(InvalidPolicyError, match="conflicts with built-in provider"):
        load_policy_config(cwd=tmp_path)


def test_custom_provider_rejects_insecure_remote_http(tmp_path: Path):
    lines = _base_policy_lines() + [
        "",
        "[custom_providers.insecure-remote]",
        'api_base = "http://remote-server.com/v1"',
    ]
    policy_file = tmp_path / "subllm.toml"
    policy_file.write_text("\n".join(lines))

    with pytest.raises(InvalidPolicyError, match="remote api_base must use https"):
        load_policy_config(cwd=tmp_path)


def test_custom_provider_rejects_priority_collision(tmp_path: Path):
    lines = _base_policy_lines() + [
        "",
        "[custom_providers.collision]",
        'api_base = "https://api.example.com/v1"',
        "priority = 10",  # collision with agy (priority 10)
    ]
    policy_file = tmp_path / "subllm.toml"
    policy_file.write_text("\n".join(lines))

    with pytest.raises(InvalidPolicyError, match="unique priorities"):
        load_policy_config(cwd=tmp_path)


def test_custom_provider_route_resolution_and_fallback(tmp_path: Path):
    lines = _base_policy_lines() + [
        "",
        "[custom_providers.vllm-local]",
        'api_base = "http://localhost:8000/v1"',
        'api_key_env = "VLLM_API_KEY"',
        'default_model = "custom-llama"',
        "priority = 35",  # after openrouter (30)
        "enabled = true",
    ]
    policy_file = tmp_path / "subllm.toml"
    policy_file.write_text("\n".join(lines))

    # Trigger policy load from tmp_path
    load_policy_config(cwd=tmp_path)
    os.environ["SUBLLM_POLICY_FILE"] = str(policy_file)
    try:
        routes = configured_routes("validator-agent", "patch-review")
        provider_ids = [r.provider for r in routes]
        assert "vllm-local" in provider_ids
        custom_route = next(r for r in routes if r.provider == "vllm-local")
        assert custom_route.model == "custom-llama"
        assert custom_route.api_base == "http://localhost:8000/v1"
        assert custom_route.transport == "openai-compatible"

        # Resolve with VLLM_API_KEY
        resolved = resolve(
            "validator-agent",
            "patch-review",
            provider="vllm-local",
            environ={"VLLM_API_KEY": "test-key-123"},
        )
        assert resolved.provider == "vllm-local"
        assert resolved.api_key == "test-key-123"
        assert resolved.model == "custom-llama"
    finally:
        os.environ.pop("SUBLLM_POLICY_FILE", None)


def test_custom_provider_keyless_resolution(tmp_path: Path):
    lines = _base_policy_lines() + [
        "",
        "[custom_providers.local-ollama]",
        'api_base = "http://127.0.0.1:11434/v1"',
        'default_model = "qwen2.5-coder"',
        "priority = 5",  # higher priority than agy
        "enabled = true",
    ]
    policy_file = tmp_path / "subllm.toml"
    policy_file.write_text("\n".join(lines))

    load_policy_config(cwd=tmp_path)
    os.environ["SUBLLM_POLICY_FILE"] = str(policy_file)
    try:
        # Keyless provider should be available even without environment keys
        resolved = resolve(
            "validator-agent",
            "patch-review",
            provider="local-ollama",
            environ={},
        )
        assert resolved.provider == "local-ollama"
        assert resolved.api_key == ""
        assert resolved.api_base == "http://127.0.0.1:11434/v1"
    finally:
        os.environ.pop("SUBLLM_POLICY_FILE", None)


def test_openai_worker_request_validation_with_custom_provider(tmp_path: Path):
    lines = _base_policy_lines() + [
        "",
        "[custom_providers.custom-llm]",
        'api_base = "https://custom.endpoint.com/v1"',
        'api_key_env = "CUSTOM_LLM_KEY"',
        'default_model = "custom-model-v1"',
        "priority = 50",
    ]
    policy_file = tmp_path / "subllm.toml"
    policy_file.write_text("\n".join(lines))

    load_policy_config(cwd=tmp_path)

    valid_request = {
        "schema": "subllm.openai-worker-request/v1",
        "provider": "custom-llm",
        "api_base": "https://custom.endpoint.com/v1",
        "wire_model": "custom-model-v1",
        "api_key": "valid-custom-key-123",
        "messages": [{"role": "user", "content": "hello"}],
        "model_parameters": {},
        "request_fields": {"user": "test-user"},
        "extra_headers": {},
        "response_format": None,
    }
    checked = _request(valid_request)
    assert checked["provider"] == "custom-llm"
    assert checked["wire_model"] == "custom-model-v1"

    # Reject mismatched api_base
    with pytest.raises(CompletionError, match="provider base is not policy-approved"):
        _request({**valid_request, "api_base": "https://attacker.com/v1"})

    # Reject unapproved model
    with pytest.raises(CompletionError, match="model is not policy-approved"):
        _request({**valid_request, "wire_model": "unapproved-model"})
