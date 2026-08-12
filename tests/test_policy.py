from __future__ import annotations

import pytest

import subllm.resolver as resolver
from subllm import MODELS, ROUTES, InvalidPolicyError, configured_routes, validate_policy
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


def test_direct_zai_precedes_openrouter_for_every_glm_route() -> None:
    for route in ROUTES.values():
        configured = configured_routes(route.application, route.function)
        assert configured[0].provider == "zai"
        assert next(item for item in configured if item.provider == "openrouter").priority == 20
