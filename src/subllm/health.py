from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
_STATE_SCHEMA = "subllm.provider-health/v1"
_STATE_FILE_ENV = "SUBLLM_HEALTH_STATE_FILE"
_PROVIDER = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
_REASON = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _clock() -> float:
    # Cooldown deadlines cross process boundaries, so a monotonic value from
    # one process cannot be compared by the next CLI invocation.
    return time.time()


def _state_path() -> Path:
    configured = os.environ.get(_STATE_FILE_ENV, "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_absolute():
            return candidate
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    root = Path(state_home).expanduser() if state_home else Path.home() / ".local" / "state"
    return root / "subllm" / "provider-health.json"


def _bounded_state(payload: Any) -> dict[str, _ProviderHealth]:
    if not isinstance(payload, dict) or set(payload) != {"schema", "providers"}:
        return {}
    if payload.get("schema") != _STATE_SCHEMA or not isinstance(payload.get("providers"), dict):
        return {}
    result: dict[str, _ProviderHealth] = {}
    for provider, row in payload["providers"].items():
        if not isinstance(provider, str) or not _PROVIDER.fullmatch(provider):
            continue
        expected = {
            "consecutive_failures", "cooldown_until", "last_latency_ms", "reason",
        }
        if not isinstance(row, dict) or set(row) != expected:
            continue
        failures = row["consecutive_failures"]
        cooldown = row["cooldown_until"]
        latency = row["last_latency_ms"]
        reason = row["reason"]
        if (
            isinstance(failures, bool)
            or not isinstance(failures, int)
            or not 0 <= failures <= 1_000_000
            or isinstance(cooldown, bool)
            or not isinstance(cooldown, (int, float))
            or not 0 <= float(cooldown) <= 32_503_680_000
            or not (
                latency is None
                or (isinstance(latency, int) and not isinstance(latency, bool) and 0 <= latency <= 3_600_000)
            )
            or not isinstance(reason, str)
            or not (reason == "" or _REASON.fullmatch(reason))
        ):
            continue
        result[provider] = _ProviderHealth(
            consecutive_failures=failures,
            cooldown_until=float(cooldown),
            last_latency_ms=latency,
            reason=reason,
        )
    return result


def _read_state(path: Path) -> dict[str, _ProviderHealth]:
    try:
        return _bounded_state(json.loads(path.read_text(encoding="utf-8")))
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}


def _write_state(path: Path, state: dict[str, _ProviderHealth]) -> None:
    payload = {
        "schema": _STATE_SCHEMA,
        "providers": {
            provider: {
                "consecutive_failures": entry.consecutive_failures,
                "cooldown_until": entry.cooldown_until,
                "last_latency_ms": entry.last_latency_ms,
                "reason": entry.reason,
            }
            for provider, entry in sorted(state.items())
            if _PROVIDER.fullmatch(provider)
        },
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _with_persisted_state(mutator=None) -> dict[str, _ProviderHealth]:
    path = _state_path()
    try:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock_path = path.with_name(f"{path.name}.lock")
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            with os.fdopen(descriptor, "r+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                state = _read_state(path)
                if mutator is not None:
                    mutator(state)
                    _write_state(path, state)
                return state
        finally:
            # fdopen owns and closes the descriptor on the normal path.  This
            # branch handles only failures before the context manager starts.
            with contextlib.suppress(OSError):
                os.close(descriptor)
    except OSError:
        # Provider health is a routing optimization, not an authority source.
        # A read-only or temporarily unavailable state directory must not make
        # every model route unusable.
        state = {provider: _ProviderHealth(**vars(entry)) for provider, entry in _HEALTH.items()}
        if mutator is not None:
            mutator(state)
        return state


def _replace_memory(state: dict[str, _ProviderHealth]) -> None:
    _HEALTH.clear()
    _HEALTH.update({provider: _ProviderHealth(**vars(entry)) for provider, entry in state.items()})


def order_by_health(
    routes: tuple[ResolvedRoute, ...],
    *,
    now: float | None = None,
) -> tuple[ResolvedRoute, ...]:
    observed_at = _clock() if now is None else now
    with _LOCK:
        _replace_memory(_with_persisted_state())
        cooling = {
            provider: state.cooldown_until > observed_at
            for provider, state in _HEALTH.items()
        }
    # A cooldown is a circuit-breaker decision, not merely a preference hint.
    # Retrying a cooling provider from every short-lived CLI process defeats
    # the shared health projection and recreates the original timeout chain.
    # Malformed or unavailable state still reads as empty, so advisory health
    # can never create an indefinite lockout.
    return tuple(route for route in routes if not cooling.get(route.provider, False))


def record_failure(
    provider: str,
    *,
    reason: str,
    latency_seconds: float,
    policy: ExecutionPolicyConfig,
    now: float | None = None,
) -> None:
    observed_at = _clock() if now is None else now
    bounded_reason = reason if _REASON.fullmatch(reason) else "provider_error"
    with _LOCK:
        def update(state: dict[str, _ProviderHealth]) -> None:
            entry = state.setdefault(provider, _ProviderHealth())
            entry.consecutive_failures += 1
            entry.last_latency_ms = max(0, min(3_600_000, round(latency_seconds * 1000)))
            entry.reason = bounded_reason
            if entry.consecutive_failures >= policy.failure_threshold:
                entry.cooldown_until = observed_at + policy.cooldown_seconds

        _replace_memory(_with_persisted_state(update))


def record_success(
    provider: str,
    *,
    latency_seconds: float,
    policy: ExecutionPolicyConfig,
    now: float | None = None,
) -> None:
    observed_at = _clock() if now is None else now
    with _LOCK:
        def update(state: dict[str, _ProviderHealth]) -> None:
            entry = state.setdefault(provider, _ProviderHealth())
            entry.consecutive_failures = 0
            entry.last_latency_ms = max(0, min(3_600_000, round(latency_seconds * 1000)))
            if latency_seconds >= policy.slow_response_seconds:
                entry.cooldown_until = observed_at + policy.cooldown_seconds
                entry.reason = "slow_response"
            else:
                entry.cooldown_until = 0.0
                entry.reason = ""

        _replace_memory(_with_persisted_state(update))


def provider_health(*, now: float | None = None) -> tuple[ProviderHealthReceipt, ...]:
    observed_at = _clock() if now is None else now
    with _LOCK:
        _replace_memory(_with_persisted_state())
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
        path = _state_path()
        with contextlib.suppress(OSError):
            path.unlink(missing_ok=True)


__all__ = ["ProviderHealthReceipt", "provider_health", "reset_provider_health"]
