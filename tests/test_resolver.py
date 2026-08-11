from __future__ import annotations

import pytest

from subllm import (
    MissingCredentialError,
    UnknownRouteError,
    available_routes,
    configured_route,
    resolve,
)


def test_direct_zai_is_selected_when_both_credentials_exist() -> None:
    route = resolve(
        "repair-agent",
        "repair-plan",
        environ={"ZAI_API_KEY": "key-id.signature", "OPENROUTER_API_KEY": "openrouter-secret"},
    )
    assert route.provider == "zai"
    assert route.litellm_model == "zai/glm-5.2"
    assert route.wire_model == "glm-5.2"


def test_openrouter_is_selected_when_zai_key_is_incomplete() -> None:
    route = resolve(
        "repair-agent",
        "repair-plan",
        environ={
            "ZAI_API_KEY": "key-id.ADD_SIGNATURE_SECRET",
            "OPENROUTER_API_KEY": "openrouter-secret",
        },
    )
    assert route.provider == "openrouter"
    assert route.litellm_model == "openrouter/z-ai/glm-5.2"
    assert route.extra_headers["X-OpenRouter-Title"] == "repair-agent"


def test_available_routes_preserves_explicit_priority() -> None:
    routes = available_routes(
        "validator-agent",
        "patch-review",
        environ={"ZAI_API_KEY": "id.secret", "OPENROUTER_API_KEY": "or-key"},
    )
    assert [(route.provider, route.model) for route in routes] == [
        ("zai", "glm-5.2"),
        ("openrouter", "glm-5.2"),
        ("openrouter", "qwen3.7-plus"),
    ]


def test_explicit_credentials_do_not_need_environment_variable_names() -> None:
    route = resolve(
        "onedev-agent",
        "code-edit",
        environ={},
        credentials={"openrouter": "from-private-file"},
    )
    assert route.provider == "openrouter"


def test_missing_credentials_report_names_not_values() -> None:
    with pytest.raises(MissingCredentialError) as caught:
        resolve("doctor-agent", "repair-proposal", environ={})
    message = str(caught.value)
    assert "OPENROUTER_API_KEY" in message
    assert "ZAI_API_KEY" in message


def test_credentials_are_redacted_from_repr_and_public_dict() -> None:
    secret = "id.never-print-this"
    route = resolve("skills-agent", "developer", environ={"ZAI_API_KEY": secret})
    assert secret not in repr(route)
    assert secret not in str(route.public_dict())
    assert route.litellm_kwargs()["api_key"] == secret


def test_configured_route_does_not_require_a_credential() -> None:
    route = configured_route("onedev-agent", "code-edit", provider="openrouter")
    assert route.litellm_model == "openrouter/z-ai/glm-5.2"


def test_unknown_route_and_disallowed_provider_fail_closed() -> None:
    with pytest.raises(UnknownRouteError):
        configured_route("unknown", "function")
    with pytest.raises(UnknownRouteError, match="does not allow provider"):
        configured_route("onedev-agent", "code-edit", provider="missing")
