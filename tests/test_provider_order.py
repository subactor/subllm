from __future__ import annotations

import pytest

from subllm import (
    ORDERABLE_PROVIDER_IDS,
    SUBLLM_PROVIDER_ORDER,
    InvalidPolicyError,
    available_provider_order,
    available_routes,
    parse_provider_order,
    provider_order,
    resolve,
)


def test_cursor_is_not_a_litellm_default_when_its_key_is_set() -> None:
    route = resolve(
        "repair-agent",
        "repair-plan",
        environ={
            "CURSOR_API_KEY": "cursor_test-not-a-secret",
            "ZAI_API_KEY": "id.signature",
            "OPENROUTER_API_KEY": "openrouter-secret",
        },
    )
    assert route.provider == "zai"
    assert ORDERABLE_PROVIDER_IDS == ("cursor", "zai", "openrouter")


def test_default_order_puts_cursor_first_when_its_key_is_present() -> None:
    environ = {
        "CURSOR_API_KEY": "cursor_test-not-a-secret",
        "ZAI_API_KEY": "id.signature",
        "OPENROUTER_API_KEY": "openrouter-secret",
    }
    assert provider_order(environ=environ) == ("cursor", "zai", "openrouter")
    assert available_provider_order(environ=environ) == ("cursor", "zai", "openrouter")


def test_default_order_keeps_zai_then_openrouter_without_cursor_key() -> None:
    environ = {
        "ZAI_API_KEY": "id.signature",
        "OPENROUTER_API_KEY": "openrouter-secret",
    }
    assert provider_order(environ=environ) == ("zai", "openrouter")
    assert available_provider_order(environ=environ) == ("zai", "openrouter")


def test_placeholder_cursor_key_does_not_change_the_default_chain() -> None:
    assert provider_order(environ={"CURSOR_API_KEY": "PLACEHOLDER", "ZAI_API_KEY": "id.signature"}) == (
        "zai",
        "openrouter",
    )


def test_explicit_order_overrides_the_cursor_default() -> None:
    environ = {
        "CURSOR_API_KEY": "cursor_test-not-a-secret",
        "ZAI_API_KEY": "id.signature",
        "OPENROUTER_API_KEY": "openrouter-secret",
        SUBLLM_PROVIDER_ORDER: "openrouter,zai",
    }
    assert provider_order(environ=environ) == ("openrouter", "zai")
    route = resolve("doctor-agent", "repair-proposal", environ=environ)
    assert route.provider == "openrouter"
    assert [item.provider for item in available_routes("doctor-agent", "repair-proposal", environ=environ)] == [
        "openrouter",
        "zai",
    ]


def test_unknown_provider_in_order_is_rejected() -> None:
    with pytest.raises(InvalidPolicyError, match="unknown provider in SUBLLM_PROVIDER_ORDER: openai"):
        parse_provider_order("cursor,openai,anthropic")
    with pytest.raises(InvalidPolicyError, match="unknown provider"):
        provider_order(environ={SUBLLM_PROVIDER_ORDER: "cursor,openai"})


def test_empty_and_duplicate_names_are_rejected() -> None:
    with pytest.raises(InvalidPolicyError, match="empty provider name"):
        parse_provider_order("cursor,,zai")
    with pytest.raises(InvalidPolicyError, match="duplicate provider"):
        parse_provider_order("zai,zai")


def test_whitespace_in_explicit_order_is_stripped() -> None:
    assert parse_provider_order(" cursor , openrouter ") == ("cursor", "openrouter")
