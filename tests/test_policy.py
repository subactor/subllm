from __future__ import annotations

from pathlib import Path

import pytest

import subllm.resolver as resolver
from subllm import MODELS, ROUTES, InvalidPolicyError, configured_routes, validate_policy
from subllm.policy_config import find_policy_file, load_policy_config
from subllm.types import RouteCandidate, RoutePolicy


def test_builtin_policy_is_valid() -> None:
    validate_policy()


def test_forbidden_model_is_catalogued_but_never_routed() -> None:
    assert MODELS["gemini-3.1-pro-preview"].forbidden is True
    candidates = (candidate for route in ROUTES.values() for candidate in route.candidates)
    assert all(candidate.model != "gemini-3.1-pro-preview" for candidate in candidates)


def test_invalid_policy_rejects_forbidden_model(monkeypatch: pytest.MonkeyPatch) -> None:
    route = RoutePolicy(
        "platform",
        "forbidden-test",
        (RouteCandidate("openrouter", "gemini-3.1-pro-preview", 10),),
    )
    monkeypatch.setattr(resolver, "ROUTES", {(route.application, route.function): route})
    with pytest.raises(InvalidPolicyError, match="forbidden model"):
        validate_policy()


def test_platform_site_audit_shares_interactive_candidate_providers() -> None:
    interactive = [(item.provider, item.model) for item in configured_routes("platform", "interactive")]
    audit = [(item.provider, item.model) for item in configured_routes("platform", "site-audit")]
    assert audit[0] == ("zai", "glm-5.3")
    assert {provider for provider, _model in audit} == {provider for provider, _model in interactive}


def test_direct_zai_glm53_precedes_cursor_and_openrouter_for_default_routes() -> None:
    configured = configured_routes("platform", "interactive")
    assert configured[0].provider == "zai"
    assert configured[0].model == "glm-5.3"
    assert configured[0].transport == "openai-compatible"
    assert configured[0].api_base == "https://api.z.ai/api/coding/paas/v4"


def test_repository_defaults_bind_strategies_to_keys() -> None:
    path = find_policy_file(cwd=Path(__file__).resolve().parents[1])
    assert path is not None
    policy = load_policy_config(cwd=path.parent)
    assert policy.providers["zai"].priority == 0
    assert policy.providers["zai"].default_model == "glm-5.3"
    assert policy.providers["cursor"].priority == 20
    assert policy.providers["cursor"].default_model == "gpt-5.6-sol"
    assert policy.providers["openrouter"].priority == 30
    assert policy.providers["openrouter"].default_model == "glm-5.2"


def test_zai_uses_the_coding_plan_endpoint() -> None:
    route = next(item for item in configured_routes("skills-agent", "developer") if item.provider == "zai")
    assert route.api_base == "https://api.z.ai/api/coding/paas/v4"
    assert route.model == "glm-5.3"


def test_process_editor_has_a_central_llm_route() -> None:
    routes = configured_routes("skills-agent", "process-editor")

    assert routes[0].provider == "zai"
    assert routes[0].model == "glm-5.3"
    assert {route.provider for route in routes} == {"zai", "cursor", "openrouter"}


def test_twinstudio_eda_nl2dsl_has_a_central_coding_route() -> None:
    routes = configured_routes("twinstudio", "eda-nl2dsl")

    assert routes[0].provider == "zai"
    assert routes[0].model == "glm-5.3"
    assert {route.provider for route in routes} == {"zai", "cursor", "openrouter"}


@pytest.mark.parametrize("function", ("preprocess", "execute"))
def test_prellm_routes_prefer_direct_zai_glm53(function: str) -> None:
    configured = configured_routes("prellm", function)
    assert configured[0].provider == "zai"
    assert configured[0].model == "glm-5.3"
    assert configured[0].wire_model == "glm-5.3"
    assert configured[0].api_base == "https://api.z.ai/api/coding/paas/v4"


def test_role_specific_openrouter_fallbacks_match_benchmark_recommendations() -> None:
    expected = {
        ("repair-agent", "repair-plan"): "glm-5.3",
        ("validator-agent", "patch-review"): "glm-5.3",
        ("validator-agent", "direct-pr-review"): "glm-5.3",
        # Host coding-agent invokes this canonical route through subllm-code-edit.
        ("onedev-agent", "code-edit"): "glm-5.3",
    }
    for (application, function), model in expected.items():
        route = next(item for item in configured_routes(application, function) if item.provider == "openrouter")
        assert route.model == model
        assert route.wire_model == f"z-ai/{model}"


@pytest.mark.parametrize("function", ("program-generation", "voice-programming"))
def test_szeptnik_routes_use_only_openai_compatible_transports(function: str) -> None:
    routes = configured_routes("szeptnik-one", function)
    assert [(route.provider, route.model) for route in routes] == [
        ("zai", "glm-5.3"),
        ("openrouter", "glm-5.2"),
    ]
    assert all(route.transport == "openai-compatible" for route in routes)


@pytest.mark.parametrize("function", ("patch-review", "direct-pr-review"))
def test_validator_routes_pin_direct_zai_glm_5_3(function: str) -> None:
    route = next(item for item in configured_routes("validator-agent", function) if item.provider == "zai")
    assert route.model == "glm-5.3"
    assert route.litellm_model == "zai/glm-5.3"
    assert route.wire_model == "glm-5.3"
    assert route.api_base == "https://api.z.ai/api/coding/paas/v4"


@pytest.mark.parametrize("function", ("assessment", "delegation", "review"))
def test_supervisor_routes_pin_direct_zai_glm_5_3(function: str) -> None:
    route = next(item for item in configured_routes("supervisor", function) if item.provider == "zai")
    assert route.model == "glm-5.3"
    assert route.litellm_model == "zai/glm-5.3"
    assert route.wire_model == "glm-5.3"
    assert route.api_base == "https://api.z.ai/api/coding/paas/v4"


@pytest.mark.parametrize(("application", "function"), sorted(ROUTES))
def test_every_registered_route_prefers_direct_zai_glm_5_3(application: str, function: str) -> None:
    route = configured_routes(application, function)[0]
    assert route.provider == "zai"
    assert route.model == "glm-5.3"
    assert route.wire_model == "glm-5.3"
    assert route.api_base == "https://api.z.ai/api/coding/paas/v4"
