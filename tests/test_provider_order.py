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


def test_resolve_prefers_direct_zai_when_all_credentials_are_available() -> None:
    route = resolve(
        "doctor-agent",
        "repair-proposal",
        environ={
            "CURSOR_API_KEY": "cursor_test-not-a-secret",
            "ZAI_API_KEY": "id.signature",
            "OPENROUTER_API_KEY": "openrouter-secret",
        },
    )
    assert route.provider == "zai"
    assert route.model == "glm-5.3"
    assert ORDERABLE_PROVIDER_IDS == (
        "zai", "agy", "codex", "claude", "cursor", "ollama", "openrouter", "codex-cli", "claude-cli", "agy-cli",
        "cursor-cli", "minis",
    )


def test_default_order_puts_direct_zai_first_when_key_present() -> None:
    environ = {
        "CURSOR_API_KEY": "cursor_test-not-a-secret",
        "ZAI_API_KEY": "id.signature",
        "OPENROUTER_API_KEY": "openrouter-secret",
    }
    assert provider_order(environ=environ) == ("zai", "cursor", "openrouter")
    assert available_provider_order(environ=environ) == ("zai", "cursor", "openrouter")


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


@pytest.mark.parametrize("function", ("code-edit", "code-context"))
def test_explicit_order_keeps_subscription_cli_before_local_despite_offset(function: str) -> None:
    from subllm import configured_routes

    order = ("agy", "codex-cli", "claude-cli", "zai", "openrouter", "ollama")
    routes = configured_routes("onedev-agent", function, environ={SUBLLM_PROVIDER_ORDER: ",".join(order)})
    providers = list(dict.fromkeys(route.provider for route in routes))
    assert "codex-cli" in providers
    assert providers == [provider for provider in order if provider in providers]
    assert providers[-1] == "ollama"
    assert [r.priority for r in routes] == sorted(r.priority for r in routes)
    assert len({r.priority for r in routes}) == len(routes)


def test_explicit_order_keeps_large_model_offset_inside_its_provider() -> None:
    from subllm import configured_routes

    routes = configured_routes("koru-agent", "planning-assistant", environ={
        SUBLLM_PROVIDER_ORDER: "openrouter,agy,ollama",
    })
    providers = list(dict.fromkeys(route.provider for route in routes))
    assert providers == ["openrouter", "agy", "ollama"]
    assert next(r for r in routes if r.model == "deepseek-v4-pro").priority < next(
        r for r in routes if r.provider == "agy"
    ).priority


def test_explicit_cli_order_does_not_bypass_quota_cooldown() -> None:
    from subllm import configured_routes
    from subllm.health import order_by_health, record_failure
    from subllm.policy_config import load_policy_config

    routes = configured_routes("onedev-agent", "code-edit", environ={
        SUBLLM_PROVIDER_ORDER: "agy,codex-cli,openrouter,ollama",
    })
    policy = load_policy_config().execution
    for _ in range(policy.failure_threshold):
        record_failure("codex-cli", reason="http_429", latency_seconds=0.1, policy=policy, now=100)
    healthy = order_by_health(tuple(routes), now=101)
    assert "codex-cli" not in [r.provider for r in healthy]
    assert healthy[0].provider == "agy"
    assert healthy[-1].provider == "ollama"
    recovered = order_by_health(tuple(routes), now=101 + policy.cooldown_seconds)
    assert "codex-cli" in [r.provider for r in recovered]
