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
    assert audit[0] == ("cursor", "gpt-5.6-sol")
    assert {provider for provider, _model in audit} == {provider for provider, _model in interactive}


def test_cursor_sol_precedes_zai_and_openrouter_for_default_routes() -> None:
    configured = configured_routes("platform", "interactive")
    assert configured[0].provider == "cursor"
    assert configured[0].model == "gpt-5.6-sol"
    assert configured[0].transport == "cursor-sdk"
    assert "openrouter" not in MODELS["gpt-5.6-sol"].providers


def test_repository_defaults_bind_strategies_to_keys() -> None:
    path = find_policy_file(cwd=Path(__file__).resolve().parents[1])
    assert path is not None
    policy = load_policy_config(cwd=path.parent)
    assert policy.providers["cursor"].priority == 0
    assert policy.providers["cursor"].default_model == "gpt-5.6-sol"
    assert policy.providers["zai"].priority == 10
    assert policy.providers["zai"].default_model == "glm-5.3"
    assert policy.providers["openrouter"].priority == 20
    assert policy.providers["openrouter"].default_model == "glm-5.2"


def test_zai_uses_the_coding_plan_endpoint() -> None:
    route = next(item for item in configured_routes("skills-agent", "developer") if item.provider == "zai")
    assert route.api_base == "https://api.z.ai/api/coding/paas/v4"


def test_every_registered_route_uses_glm_5_3_for_direct_zai() -> None:
    zai_routes = [
        (application, function)
        for (application, function), policy in ROUTES.items()
        if any(candidate.provider == "zai" for candidate in policy.candidates)
    ]
    assert zai_routes
    for application, function in zai_routes:
        route = next(item for item in configured_routes(application, function) if item.provider == "zai")
        assert route.model == "glm-5.3"
        assert route.wire_model == "glm-5.3"


def test_role_specific_openrouter_fallbacks_match_benchmark_recommendations() -> None:
    expected = {
        ("repair-agent", "repair-plan"): "glm-5.3-flash",
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


def test_twinstudio_eda_route_uses_only_openai_compatible_transports() -> None:
    routes = configured_routes("twinstudio", "eda-nl2dsl")
    assert [(route.provider, route.model) for route in routes] == [
        ("zai", "glm-5.3"),
        ("openrouter", "glm-5.2"),
    ]
    assert all(route.transport == "openai-compatible" for route in routes)


def test_twinstudio_firmware_audit_has_openai_compatible_fallback() -> None:
    routes = configured_routes("twinstudio", "eda-firmware-audit")
    assert [(route.provider, route.model) for route in routes] == [
        ("zai", "glm-5.3"), ("openrouter", "glm-5.2"),
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
