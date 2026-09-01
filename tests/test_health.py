from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

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


def test_cooling_providers_are_not_retried_by_the_next_process() -> None:
    routes = _routes()
    record_failure(
        "zai",
        reason="timeout",
        latency_seconds=12.0,
        policy=_POLICY,
        now=100.0,
    )
    record_failure(
        "openrouter",
        reason="timeout",
        latency_seconds=12.0,
        policy=_POLICY,
        now=100.0,
    )

    assert order_by_health(routes, now=101.0) == ()
    assert [route.provider for route in order_by_health(routes, now=161.0)] == [
        "zai",
        "openrouter",
    ]


def test_slow_success_is_returned_but_marks_provider_degraded() -> None:
    record_success("zai", latency_seconds=10.5, policy=_POLICY, now=100.0)

    receipt = next(item for item in provider_health(now=101.0) if item.provider == "zai")
    assert receipt.status == "degraded"
    assert receipt.reason == "slow_response"
    assert receipt.last_latency_ms == 10_500


def test_provider_cooldown_survives_a_fresh_completion_process() -> None:
    script = """
from subllm import ExecutionPolicyConfig
from subllm.health import record_failure
record_failure(
    'zai', reason='timeout', latency_seconds=30.0,
    policy=ExecutionPolicyConfig(True, 30.0, 20.0, 60.0, 1, 6), now=100.0,
)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    subprocess.run([sys.executable, "-c", script], check=True, env=environment)

    routes = _routes()
    assert order_by_health(routes, now=101.0)[0].provider == "openrouter"
    assert order_by_health(routes, now=161.0)[0].provider == "zai"


def test_persisted_health_is_secret_free_and_recovers_from_malformed_state(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_file = tmp_path / "shared-health.json"
    monkeypatch.setenv("SUBLLM_HEALTH_STATE_FILE", str(state_file))
    state_file.write_text('{"not":"the schema"}\n', encoding="utf-8")

    record_failure(
        "zai",
        reason="credential.value.must.not.persist",
        latency_seconds=12.0,
        policy=_POLICY,
        now=100.0,
    )

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload == {
        "schema": "subllm.provider-health/v1",
        "providers": {
            "zai": {
                "consecutive_failures": 1,
                "cooldown_until": 160.0,
                "last_latency_ms": 12000,
                "reason": "provider_error",
            },
        },
    }
    assert state_file.stat().st_mode & 0o777 == 0o600


def test_concurrent_processes_serialize_provider_failure_updates(tmp_path: Path, monkeypatch) -> None:
    state_file = tmp_path / "concurrent-health.json"
    monkeypatch.setenv("SUBLLM_HEALTH_STATE_FILE", str(state_file))
    script = """
from subllm import ExecutionPolicyConfig
from subllm.health import record_failure
record_failure(
    'zai', reason='timeout', latency_seconds=1.0,
    policy=ExecutionPolicyConfig(True, 30.0, 20.0, 60.0, 1, 6), now=100.0,
)
"""
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    processes = [
        subprocess.Popen([sys.executable, "-c", script], env=environment)
        for _ in range(6)
    ]
    assert [process.wait(timeout=10) for process in processes] == [0] * 6

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert payload["providers"]["zai"]["consecutive_failures"] == 6
