"""Exercise task defaults through resolution and completion, including opt-outs."""
from pathlib import Path

import pytest

from subllm import client_routes, complete, configured_routes
from subllm.client_types import CompletionResponse, _RetryableAttemptError

BOUNDED_ROLES = (
    ("todo2code", "semantic"),
    ("supervisor", "assessment"),
    ("koru-agent", "nl-to-koru-dsl"),
    ("koru-agent", "nl-to-coru-dsl"),
    ("subactor-proxy", "completion"),
)
MESSAGES = [{"role": "user", "content": "Select the matching task ID."}]


@pytest.mark.parametrize(("application", "function"), BOUNDED_ROLES)
def test_bounded_completion_sends_full_baseline_at_low_effort(monkeypatch, application, function):
    calls = []

    def invoke(route, messages, **kwargs):
        calls.append(route)
        assert messages == MESSAGES
        assert kwargs["response_format"] == {"type": "json_object"}
        return CompletionResponse('{"id":"T1"}', route.provider, route.wire_model)

    monkeypatch.setattr(client_routes, "_complete_route", invoke)
    response = complete(application, function, MESSAGES,
                        environ={"ZAI_API_KEY": "id.secret", "SUBLLM_PROVIDER_ORDER": "zai"},
                        response_format={"type": "json_object"})
    assert response.model == "glm-5.3"
    assert len(calls) == 1
    assert calls[0].api_base == "https://api.z.ai/api/coding/paas/v4"
    assert dict(calls[0].model_parameters) == {"reasoning_effort": "low"}


def test_model_scoped_full_failure_can_use_flash_model(monkeypatch):
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append(route.wire_model)
        if route.wire_model == "glm-5.3":
            raise _RetryableAttemptError("model unavailable", outcome="model_unavailable", provider_level=False)
        return CompletionResponse("ok", route.provider, route.wire_model)

    monkeypatch.setattr(client_routes, "_complete_route", invoke)
    response = complete("todo2code", "semantic", MESSAGES,
                        environ={"ZAI_API_KEY": "id.secret", "SUBLLM_PROVIDER_ORDER": "zai"})
    assert response.model == "glm-5.3-flash"
    assert calls == ["glm-5.3", "glm-5.3-flash"]


def test_explicit_full_model_stays_authoritative(monkeypatch):
    monkeypatch.setattr(client_routes, "_complete_route", lambda route, *args, **kwargs:
                        CompletionResponse("ok", route.provider, route.wire_model))
    response = complete("todo2code", "semantic", MESSAGES, model="glm-5.3",
                        environ={"ZAI_API_KEY": "id.secret", "SUBLLM_PROVIDER_ORDER": "zai"})
    assert response.provider == "zai" and response.model == "glm-5.3"


def test_account_rate_limit_skips_second_zai_model(monkeypatch):
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append((route.provider, route.wire_model))
        if route.provider == "zai":
            raise _RetryableAttemptError("rate limited", outcome="http_429")
        return CompletionResponse("ok", route.provider, route.wire_model)

    monkeypatch.setattr(client_routes, "_complete_route", invoke)
    response = complete("todo2code", "semantic", MESSAGES, environ={
        "ZAI_API_KEY": "id.secret", "OPENROUTER_API_KEY": "sk-or-test",
        "SUBLLM_PROVIDER_ORDER": "zai,openrouter",
    })
    assert response.provider == "openrouter"
    assert calls == [("zai", "glm-5.3"), ("openrouter", "z-ai/glm-5.3-flash")]


@pytest.mark.parametrize(("application", "function"), BOUNDED_ROLES)
def test_provider_order_can_prefer_local_inference(application, function):
    routes = configured_routes(application, function, environ={"SUBLLM_PROVIDER_ORDER": "ollama,zai"})
    assert routes[0].provider == "ollama"
    assert [r.model for r in routes if r.provider == "zai"] == ["glm-5.3", "glm-5.3-flash"]


@pytest.mark.parametrize(("application", "function"), (
    ("heyasa", "command"),
    ("heyasa", "decision-routing"),
    ("koru-agent", "nl-to-koru-dsl"),
    ("koru-agent", "queue-executor"),
    ("supervisor", "assessment"),
))
def test_luna_cli_is_available_after_codex_api_and_before_ollama(application, function):
    routes = configured_routes(application, function, environ={
        "SUBLLM_PROVIDER_ORDER": "codex,codex-cli,ollama",
    })

    providers = [route.provider for route in routes]
    assert providers.index("codex") < providers.index("codex-cli") < providers.index("ollama")
    cli_route = routes[providers.index("codex-cli")]
    assert cli_route.model == "gpt-6-luna"
    assert cli_route.wire_model == "gpt-6-luna"


def test_luna_cli_fallback_precedes_ollama_in_repository_default_policy():
    policy_file = Path(__file__).resolve().parents[1] / "subllm.toml"
    routes = configured_routes("supervisor", "assessment", environ={
        "SUBLLM_POLICY_FILE": str(policy_file),
        "SUBLLM_PROVIDER_ORDER": "",
    })

    providers = [route.provider for route in routes]
    assert providers.index("codex") < providers.index("codex-cli") < providers.index("ollama")


def test_heyasa_api_rate_limit_fails_over_to_luna_cli(monkeypatch):
    environ = {"SUBLLM_PROVIDER_ORDER": "codex,codex-cli,ollama"}
    candidates = configured_routes("heyasa", "command", environ=environ)
    routes = tuple(route for route in candidates if route.provider in {"codex", "codex-cli", "ollama"})
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append((route.provider, route.wire_model))
        if route.provider == "codex":
            raise _RetryableAttemptError("rate limited", outcome="http_429")
        return CompletionResponse("ok", route.provider, route.wire_model)

    monkeypatch.setattr(client_routes, "available_routes", lambda *args, **kwargs: routes)
    monkeypatch.setattr(client_routes, "order_with_last_resort", lambda available, **kwargs: available)
    monkeypatch.setattr(client_routes, "_complete_route", invoke)

    response = complete("heyasa", "command", MESSAGES, environ=environ)

    assert (response.provider, response.model) == ("codex-cli", "gpt-6-luna")
    assert calls == [("codex", "gpt-6-luna"), ("codex-cli", "gpt-6-luna")]


def test_disabled_luna_cli_provider_is_not_resolved(tmp_path):
    policy_file = Path(__file__).resolve().parents[1] / "subllm.toml"
    policy = policy_file.read_text(encoding="utf-8")
    cli_provider = "[providers.codex-cli]\nenabled = true"
    assert cli_provider in policy
    disabled_policy = tmp_path / "subllm.toml"
    disabled_policy.write_text(policy.replace(cli_provider, "[providers.codex-cli]\nenabled = false", 1),
                              encoding="utf-8")

    routes = configured_routes("supervisor", "assessment", environ={
        "SUBLLM_POLICY_FILE": str(disabled_policy),
        "SUBLLM_PROVIDER_ORDER": "",
    })

    assert "codex-cli" not in [route.provider for route in routes]


@pytest.mark.parametrize(("application", "function"), (
    ("heyasa", "command"),
    ("heyasa", "decision-routing"),
    ("koru-agent", "nl-to-koru-dsl"),
    ("koru-agent", "queue-executor"),
    ("supervisor", "assessment"),
))
def test_explicit_provider_order_can_exclude_luna_cli(application, function):
    routes = configured_routes(application, function, environ={
        "SUBLLM_PROVIDER_ORDER": "codex,ollama",
    })

    assert "codex" in [route.provider for route in routes]
    assert "codex-cli" not in [route.provider for route in routes]


@pytest.mark.parametrize(("application", "function"), (
    ("koru-agent", "planning-assistant"), ("koru-agent", "queue-executor"),
    ("koru-agent", "strategy-review"), ("koru-agent", "reflection"),
    ("onedev-agent", "code-edit"), ("repair-agent", "repair-plan"),
    ("validator-agent", "direct-pr-review"), ("supervisor", "review"),
))
def test_complex_roles_keep_full_model_and_reasoning_defaults(application, function):
    route = configured_routes(application, function, environ={"SUBLLM_PROVIDER_ORDER": "zai"})[0]
    assert route.wire_model == "glm-5.3"
    assert "reasoning_effort" not in route.model_parameters
