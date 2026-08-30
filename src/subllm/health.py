from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .policy_config import ExecutionPolicyConfig
from .types import ResolvedRoute


@dataclass(frozen=True)
class ProviderHealthReceipt:
    provider: str
    status: str
    consecutive_failures: int
    cooldown_remaining_seconds: float
    last_latency_ms: int | None
    reason: str


@dataclass
class _ProviderHealth:
    consecutive_failures: int = 0
    cooldown_until: float = 0.0
    last_latency_ms: int | None = None
    reason: str = ""


_LOCK = threading.Lock()
_HEALTH: dict[str, _ProviderHealth] = {}


def _clock() -> float:
    return time.monotonic()


def order_by_health(
    routes: tuple[ResolvedRoute, ...],
    *,
    now: float | None = None,
) -> tuple[ResolvedRoute, ...]:
    observed_at = _clock() if now is None else now
    with _LOCK:
        cooling = {
            provider: state.cooldown_until > observed_at
            for provider, state in _HEALTH.items()
        }
    return tuple(sorted(routes, key=lambda route: cooling.get(route.provider, False)))


def record_failure(
    provider: str,
    *,
    reason: str,
    latency_seconds: float,
    policy: ExecutionPolicyConfig,
    now: float | None = None,
) -> None:
    observed_at = _clock() if now is None else now
    with _LOCK:
        state = _HEALTH.setdefault(provider, _ProviderHealth())
        state.consecutive_failures += 1
        state.last_latency_ms = max(0, round(latency_seconds * 1000))
        state.reason = reason
        if state.consecutive_failures >= policy.failure_threshold:
            state.cooldown_until = observed_at + policy.cooldown_seconds


def record_success(
    provider: str,
    *,
    latency_seconds: float,
    policy: ExecutionPolicyConfig,
    now: float | None = None,
) -> None:
    observed_at = _clock() if now is None else now
    with _LOCK:
        state = _HEALTH.setdefault(provider, _ProviderHealth())
        state.consecutive_failures = 0
        state.last_latency_ms = max(0, round(latency_seconds * 1000))
        if latency_seconds >= policy.slow_response_seconds:
            state.cooldown_until = observed_at + policy.cooldown_seconds
            state.reason = "slow_response"
        else:
            state.cooldown_until = 0.0
            state.reason = ""


def provider_health(*, now: float | None = None) -> tuple[ProviderHealthReceipt, ...]:
    observed_at = _clock() if now is None else now
    with _LOCK:
        return tuple(
            ProviderHealthReceipt(
                provider=provider,
                status="degraded" if state.cooldown_until > observed_at else "healthy",
                consecutive_failures=state.consecutive_failures,
                cooldown_remaining_seconds=max(0.0, state.cooldown_until - observed_at),
                last_latency_ms=state.last_latency_ms,
                reason=state.reason,
            )
            for provider, state in sorted(_HEALTH.items())
        )


def reset_provider_health() -> None:
    with _LOCK:
        _HEALTH.clear()


__all__ = ["ProviderHealthReceipt", "provider_health", "reset_provider_health"]
