from __future__ import annotations

import re

import pytest

from subllm import (
    MODELS,
    MissingCredentialError,
    UnknownRouteError,
    available_routes,
    configured_route,
    resolve,
)


def test_direct_zai_is_selected_when_all_credentials_exist() -> None:
    route = resolve(
        "repair-agent",
        "repair-plan",
        environ={
            "CURSOR_API_KEY": "cursor_test-not-a-secret",
            "ZAI_API_KEY": "key-id.signature",
            "OPENROUTER_API_KEY": "openrouter-secret",
        },
    )
    assert route.provider == "zai"
    assert route.model == "glm-5.3"
    assert route.transport == "openai-compatible"
    assert route.wire_model == "glm-5.3"
    assert route.litellm_model == "zai/glm-5.3"


def test_openrouter_never_owns_gpt_sol() -> None:
    assert "openrouter" not in MODELS["gpt-5.6-sol"].providers
    route = resolve(
        "repair-agent",
        "repair-plan",
        environ={"OPENROUTER_API_KEY": "openrouter-secret"},
    )
    assert route.provider == "openrouter"
    assert route.model == "glm-5.3-flash"
    assert "gpt-5.6-sol" not in route.litellm_model
    assert "gpt-5.6-sol" not in route.wire_model


def test_zai_is_selected_when_cursor_missing_and_zai_valid() -> None:
    route = resolve(
        "doctor-agent",
        "repair-proposal",
        environ={"ZAI_API_KEY": "key-id.signature", "OPENROUTER_API_KEY": "openrouter-secret"},
    )
    assert route.provider == "zai"
    assert route.model == "glm-5.3"


def test_szeptnik_voice_route_uses_application_identity() -> None:
    route = resolve(
        "szeptnik-one",
        "voice-programming",
        environ={"OPENROUTER_API_KEY": "openrouter-secret"},
    )
    assert route.provider == "openrouter"
    assert route.application_name == "Szeptnik One"
    assert route.application_url == "https://github.com/tom-sapletta-com/watch"
    assert route.extra_headers["X-OpenRouter-Title"] == "Szeptnik One"


def test_zai_key_with_duplicate_id_falls_back_to_openrouter() -> None:
    route = resolve(
        "doctor-agent",
        "repair-proposal",
        environ={
            "ZAI_API_KEY": "key-id.key-id.signature",
            "OPENROUTER_API_KEY": "openrouter-secret",
        },
    )
    assert route.provider == "openrouter"
    assert route.model == "glm-5.2"


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
    assert route.litellm_model == "openrouter/z-ai/glm-5.3-flash"
    assert route.extra_headers["X-OpenRouter-Title"] == "repair-agent"


def test_openrouter_request_carries_application_identity() -> None:
    route = resolve(
        "validator-agent",
        "patch-review",
        environ={"OPENROUTER_API_KEY": "openrouter-secret"},
    )
    kwargs = route.litellm_kwargs()

    assert route.application_name == "validator-agent"
    assert route.application_url == "https://github.com/subactor/validator-agent"
    assert kwargs["user"] == "validator-agent"
    assert kwargs["extra_headers"] == {
        "HTTP-Referer": "https://github.com/subactor/validator-agent",
        "X-OpenRouter-Title": "validator-agent",
    }


def test_zai_request_carries_application_identity_and_unique_request_id() -> None:
    route = resolve("doctor-agent", "repair-proposal", environ={"ZAI_API_KEY": "id.secret"})
    first = route.provider_request_fields()
    second = route.provider_request_fields()

    assert first["user_id"] == "doctor-agent"
    assert first["request_id"] != second["request_id"]
    assert re.fullmatch(r"doctor-agent-repair-proposal-[0-9a-f]{32}", first["request_id"])
    assert route.litellm_kwargs(request_id="doctor-request-123")["extra_body"] == {
        "request_id": "doctor-request-123",
        "user_id": "doctor-agent",
    }


def test_todo2code_semantic_route_prefers_zai_without_cursor() -> None:
    route = resolve(
        "todo2code",
        "semantic",
        environ={"ZAI_API_KEY": "id.secret", "OPENROUTER_API_KEY": "or-key"},
    )
    fields = route.provider_request_fields()

    assert route.provider == "zai"
    assert route.wire_model == "glm-5.3"
    assert route.application_url == "https://github.com/autogrammar/todo2code"
    assert fields["user_id"] == "todo2code"


@pytest.mark.parametrize(
    "function",
    (
        "planning-assistant",
        "queue-executor",
        "reflection",
        "nl-to-koru-dsl",
        "nl-to-coru-dsl",
        "strategy-review",
    ),
)
def test_koru_routes_prefer_direct_zai_glm53(function: str) -> None:
    route = resolve(
        "koru-agent",
        function,
        environ={
            "CURSOR_API_KEY": "cursor_test-not-a-secret",
            "ZAI_API_KEY": "id.signature",
            "OPENROUTER_API_KEY": "openrouter-secret",
        },
    )

    assert route.provider == "zai"
    assert route.model == "glm-5.3"
    assert route.transport == "openai-compatible"
    assert route.application_name == "Koru"
    assert route.application_url == "https://github.com/semcod/koru"
    assert route.wire_model == "glm-5.3"


@pytest.mark.parametrize("function", ("oql-generation", "doctor-recommendation"))
def test_c2004_routes_use_c2004_identity(function: str) -> None:
    route = resolve(
        "c2004-system",
        function,
        environ={"ZAI_API_KEY": "id.signature", "OPENROUTER_API_KEY": "openrouter-secret"},
    )

    assert route.provider == "zai"
    assert route.model == "glm-5.3"
    assert route.application_name == "C2004"
    assert route.application_url == "https://github.com/maskservice/c2004"


def test_koru_routes_fall_back_to_openrouter_without_zai_or_cursor() -> None:
    route = resolve(
        "koru-agent",
        "planning-assistant",
        environ={"OPENROUTER_API_KEY": "openrouter-secret"},
    )
    assert route.provider == "openrouter"
    assert route.model == "glm-5.2"


@pytest.mark.parametrize("function", ("preprocess", "execute"))
def test_prellm_routes_use_public_application_identity(function: str) -> None:
    route = resolve("prellm", function, environ={"ZAI_API_KEY": "id.signature"})
    fields = route.provider_request_fields(request_id=f"prellm-{function}-request")

    assert route.provider == "zai"
    assert route.model == "glm-5.3"
    assert route.application_name == "PreLLM"
    assert route.application_url == "https://github.com/semcod/prellm"
    assert fields["user_id"] == "prellm"


def test_zai_rejects_invalid_custom_request_id_length() -> None:
    route = configured_route("doctor-agent", "repair-proposal", provider="zai")
    with pytest.raises(ValueError, match="6 to 64"):
        route.provider_request_fields(request_id="short")


def test_available_routes_skips_cursor_without_key() -> None:
    routes = available_routes(
        "validator-agent",
        "patch-review",
        environ={"ZAI_API_KEY": "id.secret", "OPENROUTER_API_KEY": "or-key"},
    )
    assert [(route.provider, route.model) for route in routes] == [
        ("zai", "glm-5.3"),
        ("openrouter", "glm-5.3"),
        ("openrouter", "qwen3.7-plus"),
    ]


def test_available_routes_prefers_direct_zai_when_all_keys_are_present() -> None:
    routes = available_routes(
        "validator-agent",
        "patch-review",
        environ={
            "CURSOR_API_KEY": "cursor_test-not-a-secret",
            "ZAI_API_KEY": "id.secret",
            "OPENROUTER_API_KEY": "or-key",
        },
    )
    assert [(route.provider, route.model) for route in routes] == [
        ("zai", "glm-5.3"),
        ("cursor", "gpt-5.6-sol"),
        ("cursor", "grok-4.6"),
        ("openrouter", "glm-5.3"),
        ("openrouter", "qwen3.7-plus"),
    ]


def test_credential_source_matrix_selects_expected_provider_model() -> None:
    """Z.AI / OpenRouter / Cursor key isolation → optimal model per source."""
    cases = (
        ({"ZAI_API_KEY": "key-id.signature"}, "zai", "glm-5.3"),
        ({"OPENROUTER_API_KEY": "openrouter-secret"}, "openrouter", "glm-5.3-flash"),
        ({"CURSOR_API_KEY": "cursor_test-not-a-secret"}, "cursor", "gpt-5.6-sol"),
        (
            {
                "CURSOR_API_KEY": "cursor_test-not-a-secret",
                "ZAI_API_KEY": "key-id.signature",
                "OPENROUTER_API_KEY": "openrouter-secret",
            },
            "zai",
            "glm-5.3",
        ),
    )
    for environ, provider, model in cases:
        route = resolve("repair-agent", "repair-plan", environ=environ)
        assert route.provider == provider
        assert route.model == model
        if provider == "openrouter":
            assert "gpt-5.6-sol" not in route.wire_model
            assert "gpt-5.6-sol" not in route.litellm_model
        if provider == "cursor":
            assert route.transport == "cursor-sdk"
            assert route.wire_model == "gpt-5.6-sol"


def test_cursor_grok_is_second_candidate_not_openrouter() -> None:
    routes = available_routes(
        "doctor-agent",
        "repair-proposal",
        environ={"CURSOR_API_KEY": "cursor_test-not-a-secret"},
    )
    assert [(r.provider, r.model, r.wire_model) for r in routes] == [
        ("cursor", "gpt-5.6-sol", "gpt-5.6-sol"),
        ("cursor", "grok-4.6", "grok-4.6"),
    ]
    assert "openrouter" not in MODELS["grok-4.6"].providers


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
    assert "CURSOR_API_KEY" in message


def test_credentials_are_redacted_from_repr_and_public_dict() -> None:
    secret = "never-print-this-openrouter-key"
    route = resolve("skills-agent", "developer", environ={"OPENROUTER_API_KEY": secret})
    assert secret not in repr(route)
    assert secret not in str(route.public_dict())
    assert route.litellm_kwargs()["api_key"] == secret


def test_configured_route_does_not_require_a_credential() -> None:
    route = configured_route("onedev-agent", "code-edit", provider="openrouter")
    assert route.litellm_model == "openrouter/z-ai/glm-5.3"


def test_unknown_route_and_disallowed_provider_fail_closed() -> None:
    with pytest.raises(UnknownRouteError):
        configured_route("unknown", "function")
    with pytest.raises(UnknownRouteError, match="does not allow provider"):
        configured_route("onedev-agent", "code-edit", provider="missing")
