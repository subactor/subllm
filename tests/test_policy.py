from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import subllm.resolver as resolver
from subllm import MODELS, ROUTES, InvalidPolicyError, configured_routes, validate_policy
from subllm.policy_config import find_policy_file, load_policy_config
from subllm.types import RouteCandidate, RoutePolicy


def test_builtin_policy_is_valid() -> None:
    validate_policy()


def test_validation_reads_one_fresh_snapshot_per_call(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = load_policy_config()
    disabled = replace(runtime, providers={
        name: replace(settings, enabled=False) for name, settings in runtime.providers.items()
    }, custom_providers={})
    observations = iter((runtime, disabled))
    loads = []

    def observe_policy():
        loads.append(None)
        return next(observations)

    monkeypatch.setattr(resolver, "load_policy_config", observe_policy)
    validate_policy()
    assert len(loads) == 1
    with pytest.raises(InvalidPolicyError, match="no enabled candidate"):
        validate_policy()
    assert len(loads) == 2


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


def test_nexu_vision_route_is_openrouter_only() -> None:
    configured = configured_routes("autogrammar-nexu", "vision")
    assert configured[0].modality == "vision"
    assert configured[0].provider == "openrouter"
    assert configured[0].model == "glm-4.5v"
    assert configured[0].transport == "openai-compatible"
    assert {route.provider for route in configured} == {"openrouter"}
    assert all(MODELS[route.model].vision for route in configured)


def test_vision_routes_exist_for_known_image_consumers() -> None:
    for application, function in (
        ("autogrammar-nexu", "vision"),
        ("autogrammar-nlp2cmd", "vision"),
        ("autogrammar-vql", "vision"),
        ("autogrammar-imgl", "vision"),
    ):
        routes = configured_routes(application, function)
        assert routes[0].modality == "vision"
        assert routes[0].model == "glm-4.5v"


def test_invalid_policy_rejects_cursor_on_vision_route(monkeypatch: pytest.MonkeyPatch) -> None:
    route = RoutePolicy(
        "autogrammar-nexu",
        "vision-cursor",
        (RouteCandidate("cursor", "gpt-5.6-sol"),),
        modality="vision",
    )
    monkeypatch.setattr(resolver, "ROUTES", {(route.application, route.function): route})
    with pytest.raises(InvalidPolicyError, match="vision route cannot use cursor-sdk"):
        validate_policy()


def test_direct_zai_glm53_precedes_cursor_and_openrouter_for_default_routes() -> None:
    configured = configured_routes("platform", "interactive")
    assert configured[0].provider == "zai"
    assert configured[0].model == "glm-5.3"
    assert configured[0].transport == "openai-compatible"
    assert configured[0].api_base == "https://api.z.ai/api/coding/paas/v4"


LOCAL_PROVIDERS = {"minis", "ollama"}


def test_koru_routes_fall_back_to_openrouter_deepseek_last() -> None:
    for function in (
        "planning-assistant",
        "queue-executor",
        "reflection",
        "nl-to-koru-dsl",
        "nl-to-coru-dsl",
        "strategy-review",
    ):
        configured = configured_routes("koru-agent", function)
        assert configured[0].provider == "zai"
        expected = "glm-5.3"
        assert configured[0].model == expected
        cloud = [route for route in configured if route.provider not in LOCAL_PROVIDERS]
        assert cloud[-1].provider == "openrouter"
        assert cloud[-1].model == "deepseek-v4-pro"
        assert cloud[-1].litellm_model == "openrouter/deepseek/deepseek-v4-pro"
        assert [route.provider for route in configured[len(cloud):]] == ["minis", "ollama"]


def test_deepseek_stays_off_non_koru_routes() -> None:
    for application, function in (
        ("platform", "interactive"),
        ("validator-agent", "direct-pr-review"),
        ("supervisor", "delegation"),
    ):
        configured = configured_routes(application, function)
        assert all(route.model != "deepseek-v4-pro" for route in configured)


def test_repository_defaults_bind_strategies_to_keys() -> None:
    path = find_policy_file(cwd=Path(__file__).resolve().parents[1])
    assert path is not None
    policy = load_policy_config(cwd=path.parent)
    assert {
        provider: settings.default_model
        for provider, settings in policy.providers.items()
    } == {
        "zai": "glm-5.3",
        "agy": "gemini-3.8-flash",
        "codex": "gpt-6-sol",
        "codex-cli": "gpt-6-sol",
        "agy-cli": "claude-sonnet-4-6",
        "claude-cli": "claude-sonnet-5",
        "claude": "claude-opus-5",
        "cursor": "gpt-5.6-sol",
        "cursor-cli": "cursor-auto",
        "ollama": "qwen3-coder:30b",
        "openrouter": "glm-5.3-flash",
    }
    assert policy.providers["zai"].priority == 0
    assert policy.providers["cursor"].priority == 20
    assert policy.providers["openrouter"].priority == 30


@pytest.mark.parametrize(
    ("model", "provider", "litellm_model", "wire_model"),
    (
        ("gemini-3.1-pro-high", "agy", "gemini/gemini-3.1-pro-preview", "gemini-3.1-pro-preview"),
        (
            "gemini-3.7-flash-medium",
            "agy",
            "gemini/gemini-3.7-flash",
            "gemini-3.7-flash",
        ),
        ("gemini-3.8-flash", "agy", "gemini/gemini-3.8-flash", "gemini-3.8-flash"),
        ("gemini-3.5-flash-lite", "agy", "gemini/gemini-3.5-flash-lite", "gemini-3.5-flash-lite"),
        ("claude-opus-5", "claude", "anthropic/claude-opus-5", "claude-opus-5"),
        ("claude-sonnet-5", "claude", "anthropic/claude-sonnet-5", "claude-sonnet-5"),
        ("gpt-6-sol", "codex", "openai/gpt-6-sol", "gpt-6-sol"),
        ("gpt-6-sol", "codex-cli", "", "gpt-6-sol"),
        ("gpt-5.6-sol", "codex", "openai/gpt-5.6-sol", "gpt-5.6-sol"),
        ("gpt-5.6-sol", "cursor", "cursor/gpt-5.6-sol", "gpt-5.6-sol"),
        ("gpt-5.6-terra", "codex", "openai/gpt-5.6-terra", "gpt-5.6-terra"),
        ("gpt-5.6-luna", "codex", "openai/gpt-5.6-luna", "gpt-5.6-luna"),
        ("qwen3-coder:30b", "ollama", "openai/qwen3-coder:30b", "qwen3-coder:30b"),
        ("grok-4.6", "cursor", "cursor/grok-4.6", "grok-4.6"),
        ("composer-2.5", "cursor", "cursor/composer-2.5", "composer-2.5"),
    ),
)
def test_three_tier_direct_model_catalog_has_exact_transport_bindings(
    model: str,
    provider: str,
    litellm_model: str,
    wire_model: str,
) -> None:
    binding = MODELS[model].providers[provider]

    assert binding.litellm_model == litellm_model
    assert binding.wire_model == wire_model


def test_direct_tier_models_do_not_invent_openrouter_aliases() -> None:
    for model in (
        "gemini-3.1-pro-high",
        "gemini-3.7-flash-medium",
        "claude-opus-5",
        "claude-sonnet-5",
        "gpt-6-sol",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "qwen3-coder:30b",
        "grok-4.6",
        "composer-2.5",
    ):
        assert "openrouter" not in MODELS[model].providers


def test_zai_uses_the_coding_plan_endpoint() -> None:
    route = next(item for item in configured_routes("skills-agent", "developer") if item.provider == "zai")
    assert route.api_base == "https://api.z.ai/api/coding/paas/v4"
    assert route.model == "glm-5.3"


def test_process_editor_has_a_central_llm_route() -> None:
    routes = configured_routes("skills-agent", "process-editor")

    assert routes[0].provider == "zai"
    assert routes[0].model == "glm-5.3"
    # Every credentialed provider is a candidate; a route only runs those with a valid key.
    assert {route.provider for route in routes} >= {"zai", "openrouter", "agy", "codex", "claude", "ollama"}


@pytest.mark.parametrize("function", ("preprocess", "execute"))
def test_prellm_routes_prefer_direct_zai_glm53(function: str) -> None:
    configured = configured_routes("prellm", function)
    assert configured[0].provider == "zai"
    assert configured[0].model == "glm-5.3"
    assert configured[0].wire_model == "glm-5.3"
    assert configured[0].api_base == "https://api.z.ai/api/coding/paas/v4"


def test_role_specific_openrouter_fallbacks_are_explicit() -> None:
    expected = {
        ("repair-agent", "repair-plan"): "glm-5.3",
        ("validator-agent", "patch-review"): "glm-5.3-flash",
        ("validator-agent", "direct-pr-review"): "glm-5.3-flash",
        # Host coding-agent invokes this canonical route through subllm-code-edit.
        ("onedev-agent", "code-edit"): "glm-5.3",
        ("onedev-agent", "code-context"): "glm-5.3-flash",
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
        ("zai", "glm-5.3-flash"),
        ("openrouter", "glm-5.3-flash"),
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
def test_supervisor_routes_choose_models_by_role(function: str) -> None:
    route = next(item for item in configured_routes("supervisor", function) if item.provider == "zai")
    expected = "glm-5.3"
    assert route.model == route.wire_model == expected
    assert route.litellm_model == f"zai/{expected}"
    assert route.api_base == "https://api.z.ai/api/coding/paas/v4"


@pytest.mark.parametrize(("application", "function"), sorted(ROUTES))
def test_every_registered_route_prefers_its_declared_model_role(application: str, function: str) -> None:
    policy = ROUTES[(application, function)]
    if (application, function) == ("subactor-proxy", "deepseek-flash"):
        route = configured_routes(application, function)[0]
        assert route.provider == "openrouter"
        assert route.wire_model == "deepseek/deepseek-v4.1-flash"
        return
    if (application, function) == ("organism-guard", "refactor"):
        route = configured_routes(application, function)[0]
        assert route.provider == route.transport == "codex-cli"
        assert route.model == "gpt-6-sol"
        return
    if policy.modality == "vision":
        route = configured_routes(application, function)[0]
        assert route.provider == "openrouter"
        assert route.model == "glm-4.5v"
        assert route.litellm_model == "openrouter/z-ai/glm-4.5v"
        assert route.wire_model == "z-ai/glm-4.5v"
        assert route.modality == "vision"
        return
    route = configured_routes(application, function)[0]
    assert route.provider == "zai"
    bounded = (application, function) in {
        ("todo2code", "semantic"), ("supervisor", "assessment"),
        ("koru-agent", "nl-to-koru-dsl"), ("koru-agent", "nl-to-coru-dsl"),
        ("subactor-proxy", "completion"),
    }
    expected = "glm-5.3"
    if bounded:
        assert route.model_parameters["reasoning_effort"] == "low"
    assert route.model == route.wire_model == expected
    assert route.api_base == "https://api.z.ai/api/coding/paas/v4"


def test_twinstudio_declares_every_runtime_route() -> None:
    assert {
        function
        for application, function in ROUTES
        if application == "twinstudio"
    } == {"eda-nl2dsl", "eda-firmware-audit", "eda-conflict-chat"}


def test_supervisor_assessment_bounds_only_direct_zai_reasoning() -> None:
    assessment = configured_routes("supervisor", "assessment")
    delegation = configured_routes("supervisor", "delegation")
    assert sorted((r.provider, r.model, r.wire_model) for r in assessment) == sorted(
        (r.provider, r.model, r.wire_model) for r in delegation
    )
    previous_by_model = {(r.provider, r.model): r for r in delegation}
    for current in assessment:
        previous = previous_by_model[(current.provider, current.model)]
        assert dict(current.model_parameters) == (
            {"reasoning_effort": "low"}
            if current.provider == "zai" else dict(previous.model_parameters)
        )
    for function in ("delegation", "review"):
        assert all(
            "reasoning_effort" not in r.model_parameters
            for r in configured_routes("supervisor", function)
        )
    assert all(
        "reasoning_effort" not in r.model_parameters
        for r in configured_routes("repair-agent", "repair-plan")
    )


def test_context_selection_has_its_own_role_without_changing_edit_routes() -> None:
    env = {"SUBLLM_PROVIDER_ORDER": "openrouter,cursor,zai"}
    context = configured_routes("onedev-agent", "code-context", environ=env)
    editing = configured_routes("onedev-agent", "code-edit", environ=env)
    assert context[0].wire_model == "z-ai/glm-5.3-flash"
    assert dict(context[0].model_parameters) == {"reasoning_effort": "low"}
    assert dict(editing[0].model_parameters) == {}
    assert editing[0].wire_model == "z-ai/glm-5.3"
    assert [(r.provider, r.wire_model) for r in context[1:]] == [
        (r.provider, r.wire_model) for r in editing if r.provider != "openrouter" or r.wire_model != "z-ai/glm-5.3"
    ][1:]


def test_wellman_standard_selection_has_own_identity_and_default_candidates() -> None:
    from subllm.policy import APPLICATIONS
    assert APPLICATIONS['wellman'].url == 'https://github.com/wellmanifest/wellman'
    advice = configured_routes('wellman', 'standard-selection')
    defaults = configured_routes('doctor-agent', 'repair-proposal')
    assert [(item.provider, item.model) for item in advice] == [(item.provider, item.model) for item in defaults]
    assert all(item.application == 'wellman' and item.function == 'standard-selection' for item in advice)
    validate_policy()
