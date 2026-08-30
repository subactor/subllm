from __future__ import annotations

from subllm import (
    ExecutionPolicyConfig,
    available_routes,
    provider_health,
)
from subllm.health import order_by_health, record_failure, record_success

_POLICY = ExecutionPolicyConfig(
    failover_enabled=True,
    attempt_timeout_seconds=12.0,
    slow_response_seconds=10.0,
    cooldown_seconds=60.0,
    failure_threshold=1,
    max_attempts=6,
)


def _routes():
    return available_routes(
        "todo2code",
        "semantic",
        environ={
            "ZAI_API_KEY": "id.secret",
            "OPENROUTER_API_KEY": "sk-or-v1-testkey",
        },
    )


def test_provider_recovers_to_policy_order_after_cooldown() -> None:
    routes = _routes()
    assert routes[0].provider == "zai"
    record_failure(
        "zai",
        reason="timeout",
        latency_seconds=12.0,
        policy=_POLICY,
        now=100.0,
    )

    assert order_by_health(routes, now=101.0)[0].provider == "openrouter"
    assert order_by_health(routes, now=161.0)[0].provider == "zai"


def test_slow_success_is_returned_but_marks_provider_degraded() -> None:
    record_success("zai", latency_seconds=10.5, policy=_POLICY, now=100.0)

    receipt = next(item for item in provider_health(now=101.0) if item.provider == "zai")
    assert receipt.status == "degraded"
    assert receipt.reason == "slow_response"
    assert receipt.last_latency_ms == 10_500
