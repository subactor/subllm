"""Tests and regression canaries for OpenAI codex provider with gpt-6-luna and gpt-6.1-terra."""

from unittest.mock import patch

from subllm.client_types import CompletionResponse
from subllm.policy import MODELS
from subllm.resolver import configured_routes, resolve


def test_codex_models_spec() -> None:
    """Verify that gpt-6-luna and gpt-6.1-terra are properly registered for codex."""
    assert "gpt-6-luna" in MODELS
    luna = MODELS["gpt-6-luna"]
    assert "codex" in luna.providers
    assert luna.providers["codex"].wire_model == "gpt-6-luna"
    assert luna.providers["codex"].litellm_model == "openai/gpt-6-luna"

    assert "gpt-6.1-terra" in MODELS
    terra = MODELS["gpt-6.1-terra"]
    assert "codex" in terra.providers
    assert terra.providers["codex"].wire_model == "gpt-6.1-terra"
    assert terra.providers["codex"].litellm_model == "openai/gpt-6.1-terra"


def test_codex_canary_routing_resolution() -> None:
    """Verify resolver routes koru-agent queue-executor to gpt-6-luna under codex order."""
    token_val = "sk-test-mock-token"
    res = resolve(
        "koru-agent",
        "queue-executor",
        environ={"SUBLLM_PROVIDER_ORDER": "codex,zai", "OPENAI_API_KEY": token_val},
    )
    assert res.provider == "codex"
    assert res.model == "gpt-6-luna"
    assert res.wire_model == "gpt-6-luna"


def test_codex_terra_explicit_model_selection() -> None:
    """Verify szeptnik route declares gpt-6.1-terra as a candidate."""
    routes = configured_routes("szeptnik-one", "program-generation")
    terra_routes = [r for r in routes if r.provider == "codex" and r.model == "gpt-6.1-terra"]
    assert len(terra_routes) == 1
    assert terra_routes[0].wire_model == "gpt-6.1-terra"


def test_codex_canary_mocked_completion() -> None:
    """Verify complete() invocation with codex gpt-6-luna parses completion and usage."""
    from subllm.client_routes import complete

    mock_resp = CompletionResponse(
        content='{"status": "ok"}',
        provider="codex",
        model="gpt-6-luna",
        finish_reason="stop",
        usage={"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
        attempts=1,
    )

    with patch("subllm.client_routes._complete_route", return_value=mock_resp):
        res = complete(
            application="koru-agent",
            function="queue-executor",
            messages=[{"role": "user", "content": "test"}],
            credentials={"codex": "sk-test-mock-credential"},
        )
        assert res.provider == "codex"
        assert res.model == "gpt-6-luna"
        assert res.content == '{"status": "ok"}'
        assert res.usage["total_tokens"] == 30
