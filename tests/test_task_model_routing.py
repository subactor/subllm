"""Exercise task defaults through resolution and completion, including opt-outs."""
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
    ("koru-agent", "planning-assistant"), ("koru-agent", "queue-executor"),
    ("koru-agent", "strategy-review"), ("koru-agent", "reflection"),
    ("onedev-agent", "code-edit"), ("repair-agent", "repair-plan"),
    ("validator-agent", "direct-pr-review"), ("supervisor", "review"),
))
def test_complex_roles_keep_full_model_and_reasoning_defaults(application, function):
    route = configured_routes(application, function, environ={"SUBLLM_PROVIDER_ORDER": "zai"})[0]
    assert route.wire_model == "glm-5.3"
    assert "reasoning_effort" not in route.model_parameters
