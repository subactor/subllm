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
    assert policy.providers["openrouter"].priority == 20
    assert policy.providers["openrouter"].default_model == "glm-5.2"


def test_zai_uses_the_coding_plan_endpoint() -> None:
    route = next(item for item in configured_routes("skills-agent", "developer") if item.provider == "zai")
    assert route.api_base == "https://api.z.ai/api/coding/paas/v4"
