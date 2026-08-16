from __future__ import annotations

from collections.abc import Mapping

from .credential_env import credential_is_valid, merged_environment
from .errors import InvalidPolicyError
from .policy import CURSOR_API_KEY_ENV, ORDERABLE_PROVIDER_IDS, PROVIDERS, SUBLLM_PROVIDER_ORDER


def parse_provider_order(raw: str) -> tuple[str, ...]:
    parts = [item.strip() for item in raw.split(",")]
    if not parts or any(not part for part in parts):
        raise InvalidPolicyError(f"empty provider name in {SUBLLM_PROVIDER_ORDER}")
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        if part not in ORDERABLE_PROVIDER_IDS:
            raise InvalidPolicyError(f"unknown provider in {SUBLLM_PROVIDER_ORDER}: {part}")
        if part in seen:
            raise InvalidPolicyError(f"duplicate provider in {SUBLLM_PROVIDER_ORDER}: {part}")
        seen.add(part)
        ordered.append(part)
    return tuple(ordered)


def default_provider_order(*, environ: Mapping[str, str]) -> tuple[str, ...]:
    if credential_is_valid("cursor", environ.get(CURSOR_API_KEY_ENV)):
        return ORDERABLE_PROVIDER_IDS
    return tuple(name for name in ORDERABLE_PROVIDER_IDS if name != "cursor")


def explicit_provider_order(*, environ: Mapping[str, str]) -> tuple[str, ...] | None:
    raw = environ.get(SUBLLM_PROVIDER_ORDER, "").strip()
    if not raw:
        return None
    return parse_provider_order(raw)


def provider_order(
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    environment = merged_environment(environ=environ)
    explicit = explicit_provider_order(environ=environment)
    if explicit is not None:
        return explicit
    return default_provider_order(environ=environment)


def routing_provider_order(*, environ: Mapping[str, str]) -> tuple[str, ...] | None:
    """Return an explicit order for resolve(), or None to use subllm.toml priorities."""
    return explicit_provider_order(environ=environ)


def available_provider_order(
    *,
    environ: Mapping[str, str] | None = None,
    credentials: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    environment = merged_environment(environ=environ)
    explicit = credentials or {}
    available: list[str] = []
    for name in provider_order(environ=environment):
        value = explicit.get(name, environment.get(PROVIDERS[name].api_key_env, ""))
        if credential_is_valid(name, value):
            available.append(name)
    return tuple(available)
