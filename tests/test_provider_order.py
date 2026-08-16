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


def test_resolve_returns_cursor_when_cursor_key_and_sol_route() -> None:
    route = resolve(
        "doctor-agent",
        "repair-proposal",
        environ={
            "CURSOR_API_KEY": "cursor_test-not-a-secret",
            "ZAI_API_KEY": "id.signature",
            "OPENROUTER_API_KEY": "openrouter-secret",
        },
    )
    assert route.provider == "cursor"
    assert route.model == "gpt-5.6-sol"
    assert ORDERABLE_PROVIDER_IDS == ("cursor", "zai", "openrouter")


def test_default_order_puts_cursor_first_when_key_present() -> None:
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


def test_placeholder_cursor_key_does_not_enable_cursor_in_default_order() -> None:
    assert provider_order(environ={"CURSOR_API_KEY": "PLACEHOLDER", "ZAI_API_KEY": "id.signature"}) == (
        "zai",
        "openrouter",
    )


def test_explicit_order_reorders_resolve_candidates() -> None:
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


def test_empty_and_duplicate_provider_names_fail_closed() -> None:
    with pytest.raises(InvalidPolicyError, match="empty provider name"):
        parse_provider_order("cursor,,zai")
    with pytest.raises(InvalidPolicyError, match="duplicate provider"):
        parse_provider_order("zai,zai")


def test_parse_provider_order_trims_whitespace() -> None:
    assert parse_provider_order(" cursor , openrouter ") == ("cursor", "openrouter")
