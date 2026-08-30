from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

from .errors import InvalidPolicyError
from .policy import APPLICATIONS, MODELS, PROVIDERS

SUBLLM_POLICY_FILE = "SUBLLM_POLICY_FILE"


@dataclass(frozen=True)
class ProviderPolicyConfig:
    enabled: bool
    priority: int
    default_model: str


@dataclass(frozen=True)
class ApplicationPolicyConfig:
    name: str
    url: str


@dataclass(frozen=True)
class ExecutionPolicyConfig:
    failover_enabled: bool
    attempt_timeout_seconds: float
    slow_response_seconds: float
    cooldown_seconds: float
    failure_threshold: int
    max_attempts: int


@dataclass(frozen=True)
class RuntimePolicyConfig:
    providers: Mapping[str, ProviderPolicyConfig]
    applications: Mapping[str, ApplicationPolicyConfig]
    execution: ExecutionPolicyConfig
    source: Path | None = None


_DEFAULTS = MappingProxyType(
    {
        "zai": ProviderPolicyConfig(enabled=True, priority=0, default_model="glm-5.3"),
        "cursor": ProviderPolicyConfig(enabled=True, priority=20, default_model="gpt-5.6-sol"),
        "openrouter": ProviderPolicyConfig(enabled=True, priority=30, default_model="glm-5.2"),
    }
)

_APPLICATION_DEFAULTS = MappingProxyType(
    {
        name: ApplicationPolicyConfig(name=application.title, url=application.url)
        for name, application in APPLICATIONS.items()
    }
)

_EXECUTION_DEFAULTS = ExecutionPolicyConfig(
    failover_enabled=True,
    attempt_timeout_seconds=12.0,
    slow_response_seconds=10.0,
    cooldown_seconds=60.0,
    failure_threshold=1,
    max_attempts=6,
)


def find_policy_file(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path | None:
    environment = os.environ if environ is None else environ
    working_directory = (cwd or Path.cwd()).resolve()
    configured = environment.get(SUBLLM_POLICY_FILE, "").strip()
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute():
            path = working_directory / path
        return path.absolute()

    repository_policy = working_directory / "subllm.toml"
    if repository_policy.is_file():
        return repository_policy

    for root in (working_directory, *working_directory.parents):
        candidates = [root / "subllm" / "subllm.toml"]
        if root.name == "subllm":
            candidates.insert(0, root / "subllm.toml")
        for candidate in candidates:
            if candidate.is_file():
                return candidate
    return None


def _validate_provider(name: str, raw: object, *, source: Path) -> ProviderPolicyConfig:
    if not isinstance(raw, dict) or set(raw) != {"enabled", "priority", "default_model"}:
        raise InvalidPolicyError(f"invalid provider settings for {name} in {source}")
    enabled = raw["enabled"]
    priority = raw["priority"]
    default_model = raw["default_model"]
    if not isinstance(enabled, bool):
        raise InvalidPolicyError(f"provider {name} enabled must be boolean in {source}")
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 10_000:
        raise InvalidPolicyError(f"provider {name} priority must be an integer from 0 to 10000 in {source}")
    if not isinstance(default_model, str) or default_model not in MODELS:
        raise InvalidPolicyError(f"unknown default model for provider {name} in {source}")
    model = MODELS[default_model]
    if model.forbidden:
        raise InvalidPolicyError(f"forbidden default model for provider {name}: {default_model}")
    if name not in model.providers:
        raise InvalidPolicyError(f"model {default_model} is unavailable through provider {name}")
    return ProviderPolicyConfig(enabled=enabled, priority=priority, default_model=default_model)


def _validate_application(name: str, raw: object, *, source: Path) -> ApplicationPolicyConfig:
    if not 6 <= len(name) <= 128:
        raise InvalidPolicyError(f"application ID {name} must contain 6 to 128 characters")
    if not isinstance(raw, dict) or set(raw) != {"name", "url"}:
        raise InvalidPolicyError(f"invalid application settings for {name} in {source}")
    display_name = raw["name"]
    url = raw["url"]
    if not isinstance(display_name, str) or not display_name or display_name != display_name.strip():
        raise InvalidPolicyError(f"application {name} name must be a non-empty trimmed string in {source}")
    if len(display_name) > 100:
        raise InvalidPolicyError(f"application {name} name must not exceed 100 characters in {source}")
    if not isinstance(url, str):
        raise InvalidPolicyError(f"application {name} URL must be HTTPS in {source}")
    parsed = urlsplit(url)
    invalid_url = (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    )
    if invalid_url:
        raise InvalidPolicyError(
            f"application {name} URL must be a public HTTPS URL without credentials or query in {source}"
        )
    return ApplicationPolicyConfig(name=display_name, url=url)


def _bounded_number(
    raw: object,
    *,
    name: str,
    minimum: float,
    maximum: float,
    source: Path,
) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise InvalidPolicyError(f"execution {name} must be a number in {source}")
    value = float(raw)
    if not minimum <= value <= maximum:
        raise InvalidPolicyError(
            f"execution {name} must be from {minimum:g} to {maximum:g} in {source}"
        )
    return value


def _validate_execution(raw: object, *, source: Path) -> ExecutionPolicyConfig:
    expected = {
        "failover_enabled",
        "attempt_timeout_seconds",
        "slow_response_seconds",
        "cooldown_seconds",
        "failure_threshold",
        "max_attempts",
    }
    if not isinstance(raw, dict) or set(raw) != expected:
        raise InvalidPolicyError(f"invalid execution settings in {source}")
    enabled = raw["failover_enabled"]
    if not isinstance(enabled, bool):
        raise InvalidPolicyError(f"execution failover_enabled must be boolean in {source}")
    failure_threshold = raw["failure_threshold"]
    max_attempts = raw["max_attempts"]
    if (
        isinstance(failure_threshold, bool)
        or not isinstance(failure_threshold, int)
        or not 1 <= failure_threshold <= 10
    ):
        raise InvalidPolicyError(f"execution failure_threshold must be an integer from 1 to 10 in {source}")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 10:
        raise InvalidPolicyError(f"execution max_attempts must be an integer from 1 to 10 in {source}")
    attempt_timeout = _bounded_number(
        raw["attempt_timeout_seconds"],
        name="attempt_timeout_seconds",
        minimum=0.1,
        maximum=3600.0,
        source=source,
    )
    slow_response = _bounded_number(
        raw["slow_response_seconds"],
        name="slow_response_seconds",
        minimum=0.1,
        maximum=3600.0,
        source=source,
    )
    if slow_response > attempt_timeout:
        raise InvalidPolicyError(
            f"execution slow_response_seconds must not exceed attempt_timeout_seconds in {source}"
        )
    return ExecutionPolicyConfig(
        failover_enabled=enabled,
        attempt_timeout_seconds=attempt_timeout,
        slow_response_seconds=slow_response,
        cooldown_seconds=_bounded_number(
            raw["cooldown_seconds"],
            name="cooldown_seconds",
            minimum=0.0,
            maximum=86_400.0,
            source=source,
        ),
        failure_threshold=failure_threshold,
        max_attempts=max_attempts,
    )


def load_policy_config(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> RuntimePolicyConfig:
    source = find_policy_file(environ=environ, cwd=cwd)
    if source is None:
        return RuntimePolicyConfig(
            providers=_DEFAULTS,
            applications=_APPLICATION_DEFAULTS,
            execution=_EXECUTION_DEFAULTS,
        )
    try:
        with source.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise InvalidPolicyError(f"SubLLM policy file does not exist: {source}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise InvalidPolicyError(f"cannot read SubLLM policy file: {source}") from exc
    schema_version = raw.get("schema_version")
    expected_keys = {"schema_version", "providers", "applications"}
    if schema_version == 3:
        expected_keys.add("execution")
    if set(raw) != expected_keys or schema_version not in {2, 3}:
        raise InvalidPolicyError(f"invalid SubLLM policy schema in {source}")
    provider_rows = raw.get("providers")
    if not isinstance(provider_rows, dict) or set(provider_rows) != set(PROVIDERS):
        raise InvalidPolicyError(f"SubLLM policy must configure exactly: {', '.join(PROVIDERS)}")
    providers = {
        name: _validate_provider(name, provider_rows[name], source=source)
        for name in PROVIDERS
    }
    application_rows = raw.get("applications")
    if not isinstance(application_rows, dict) or set(application_rows) != set(APPLICATIONS):
        raise InvalidPolicyError(f"SubLLM policy must configure exactly these applications: {', '.join(APPLICATIONS)}")
    applications = {
        name: _validate_application(name, application_rows[name], source=source)
        for name in APPLICATIONS
    }
    enabled_priorities = [settings.priority for settings in providers.values() if settings.enabled]
    if len(enabled_priorities) != len(set(enabled_priorities)):
        raise InvalidPolicyError(f"enabled providers must have unique priorities in {source}")
    return RuntimePolicyConfig(
        providers=MappingProxyType(providers),
        applications=MappingProxyType(applications),
        execution=(
            _validate_execution(raw["execution"], source=source)
            if schema_version == 3
            else _EXECUTION_DEFAULTS
        ),
        source=source,
    )
