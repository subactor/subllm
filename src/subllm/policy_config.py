from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

from .errors import InvalidPolicyError
from .policy import (
    APPLICATIONS,
    MODELS,
    ProviderSpec,
    clear_custom_providers,
    register_custom_provider,
)

SUBLLM_POLICY_FILE = "SUBLLM_POLICY_FILE"
SUBLLM_ATTEMPT_TIMEOUT_SECONDS = "SUBLLM_ATTEMPT_TIMEOUT_SECONDS"
SUBLLM_SLOW_RESPONSE_SECONDS = "SUBLLM_SLOW_RESPONSE_SECONDS"
_CUSTOM_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\.-]{0,63}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class ProviderPolicyConfig:
    enabled: bool
    priority: int
    default_model: str


@dataclass(frozen=True)
class CustomProviderConfig:
    id: str
    api_base: str
    api_key_env: str = ""
    default_model: str = ""
    models: tuple[str, ...] = ()
    priority: int = 50
    enabled: bool = True
    routes: tuple[str, ...] = ("all",)


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
    custom_providers: Mapping[str, CustomProviderConfig] = MappingProxyType({})
    source: Path | None = None


_DEFAULTS = MappingProxyType(
    {
        "zai": ProviderPolicyConfig(enabled=True, priority=0, default_model="glm-5.3"),
        "agy": ProviderPolicyConfig(enabled=True, priority=10, default_model="gemini-3.1-pro-high"),
        "codex-cli": ProviderPolicyConfig(enabled=True, priority=16, default_model="gpt-5.6-sol"),
        # CLI-authenticated executors spend a subscription, so they stay off until the operator opts in.
        "agy-cli": ProviderPolicyConfig(enabled=False, priority=12, default_model="claude-sonnet-4-6"),
        "claude-cli": ProviderPolicyConfig(enabled=False, priority=17, default_model="claude-sonnet-5"),
        "codex": ProviderPolicyConfig(enabled=True, priority=15, default_model="gpt-5.6-sol"),
        "claude": ProviderPolicyConfig(enabled=True, priority=18, default_model="claude-opus-5"),
        "cursor": ProviderPolicyConfig(enabled=True, priority=20, default_model="gpt-5.6-sol"),
        "ollama": ProviderPolicyConfig(enabled=True, priority=25, default_model="qwen3-coder:30b"),
        "openrouter": ProviderPolicyConfig(enabled=True, priority=30, default_model="glm-5.3-flash"),
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


def _environment_number(
    environment: Mapping[str, str],
    name: str,
    default: float,
) -> float:
    raw = environment.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise InvalidPolicyError(f"runtime {name} must be a number") from exc
    if not 0.1 <= value <= 3600.0:
        raise InvalidPolicyError(f"runtime {name} must be from 0.1 to 3600")
    return value


def _execution_with_environment(
    execution: ExecutionPolicyConfig,
    environ: Mapping[str, str] | None,
) -> ExecutionPolicyConfig:
    environment = os.environ if environ is None else environ
    attempt_timeout = _environment_number(
        environment,
        SUBLLM_ATTEMPT_TIMEOUT_SECONDS,
        execution.attempt_timeout_seconds,
    )
    slow_response = _environment_number(
        environment,
        SUBLLM_SLOW_RESPONSE_SECONDS,
        execution.slow_response_seconds,
    )
    if slow_response > attempt_timeout:
        raise InvalidPolicyError(
            f"runtime {SUBLLM_SLOW_RESPONSE_SECONDS} must not exceed "
            f"{SUBLLM_ATTEMPT_TIMEOUT_SECONDS}"
        )
    return ExecutionPolicyConfig(
        failover_enabled=execution.failover_enabled,
        attempt_timeout_seconds=attempt_timeout,
        slow_response_seconds=slow_response,
        cooldown_seconds=execution.cooldown_seconds,
        failure_threshold=execution.failure_threshold,
        max_attempts=execution.max_attempts,
    )


def find_policy_file(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> Path | None:
    environment = os.environ if environ is None else environ
    try:
        working_directory = (cwd or Path.cwd()).resolve()
    except Exception:
        working_directory = (cwd or Path.home()).resolve()
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


def _validate_custom_provider(name: str, raw: object, *, source: Path) -> CustomProviderConfig:
    if not isinstance(name, str) or not _CUSTOM_ID_RE.match(name):
        raise InvalidPolicyError(f"invalid custom provider name '{name}' in {source}")
    if name in _DEFAULTS:
        raise InvalidPolicyError(f"custom provider '{name}' conflicts with built-in provider in {source}")
    if not isinstance(raw, dict):
        raise InvalidPolicyError(f"custom provider '{name}' must be a table in {source}")
    allowed_fields = {"api_base", "api_key_env", "default_model", "models", "priority", "enabled", "routes"}
    unknown = set(raw) - allowed_fields
    if unknown:
        raise InvalidPolicyError(f"unknown fields {unknown} for custom provider '{name}' in {source}")
    if "api_base" not in raw:
        raise InvalidPolicyError(f"custom provider '{name}' missing required field 'api_base' in {source}")
    api_base = raw["api_base"]
    if not isinstance(api_base, str) or not api_base.strip():
        raise InvalidPolicyError(f"custom provider '{name}' api_base must be a non-empty string in {source}")
    api_base = api_base.strip()
    parsed = urlsplit(api_base)
    is_localhost = (
        parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        or (parsed.netloc and parsed.netloc.split(":")[0] in {"localhost", "127.0.0.1", "::1"})
    )
    if is_localhost:
        if parsed.scheme not in {"http", "https"}:
            raise InvalidPolicyError(f"custom provider '{name}' localhost api_base must use http or https in {source}")
    else:
        if parsed.scheme != "https":
            raise InvalidPolicyError(f"custom provider '{name}' remote api_base must use https in {source}")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.netloc:
        raise InvalidPolicyError(
            f"custom provider '{name}' api_base must not contain credentials, query or fragment in {source}"
        )

    api_key_env = raw.get("api_key_env", "")
    if not isinstance(api_key_env, str):
        raise InvalidPolicyError(f"custom provider '{name}' api_key_env must be string in {source}")
    api_key_env = api_key_env.strip()
    if api_key_env and not _ENV_NAME_RE.match(api_key_env):
        raise InvalidPolicyError(
            f"custom provider '{name}' api_key_env '{api_key_env}' is not a valid environment variable name in {source}"
        )

    raw_models = raw.get("models")
    if raw_models is not None:
        if not isinstance(raw_models, (list, tuple)) or not raw_models:
            raise InvalidPolicyError(f"custom provider '{name}' models must be a non-empty list in {source}")
        models = tuple(str(m).strip() for m in raw_models)
        if any(not m for m in models):
            raise InvalidPolicyError(f"custom provider '{name}' model names cannot be empty in {source}")
    else:
        models = ()

    default_model = raw.get("default_model", "")
    if not isinstance(default_model, str):
        raise InvalidPolicyError(f"custom provider '{name}' default_model must be string in {source}")
    default_model = default_model.strip()
    if not default_model:
        default_model = models[0] if models else name
    if default_model not in models:
        models = (default_model, *models)

    priority = raw.get("priority", 50)
    if isinstance(priority, bool) or not isinstance(priority, int) or not 0 <= priority <= 10_000:
        raise InvalidPolicyError(f"custom provider '{name}' priority must be an integer from 0 to 10000 in {source}")

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise InvalidPolicyError(f"custom provider '{name}' enabled must be boolean in {source}")

    raw_routes = raw.get("routes")
    if raw_routes is not None:
        if not isinstance(raw_routes, (list, tuple)):
            raise InvalidPolicyError(f"custom provider '{name}' routes must be a list in {source}")
        routes = tuple(str(r).strip() for r in raw_routes)
    else:
        routes = ("all",)

    return CustomProviderConfig(
        id=name,
        api_base=api_base.rstrip("/"),
        api_key_env=api_key_env,
        default_model=default_model,
        models=models,
        priority=priority,
        enabled=enabled,
        routes=routes,
    )


def load_policy_config(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> RuntimePolicyConfig:
    source = find_policy_file(environ=environ, cwd=cwd)
    if source is None:
        clear_custom_providers()
        return RuntimePolicyConfig(
            providers=_DEFAULTS,
            applications=_APPLICATION_DEFAULTS,
            execution=_execution_with_environment(_EXECUTION_DEFAULTS, environ),
            custom_providers=MappingProxyType({}),
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
    allowed_keys = expected_keys | {"custom_providers"}
    if not (expected_keys <= set(raw) <= allowed_keys) or schema_version not in {2, 3}:
        raise InvalidPolicyError(f"invalid SubLLM policy schema in {source}")
    provider_rows = raw.get("providers")
    # Older operator policies remain valid and do not enable a new local executor.
    for executor in ("codex-cli", "claude-cli", "agy-cli"):
        if isinstance(provider_rows, dict) and executor not in provider_rows:
            provider_rows = {**provider_rows, executor: {**asdict(_DEFAULTS[executor]), "enabled": False}}
    if not isinstance(provider_rows, dict) or set(provider_rows) != set(_DEFAULTS):
        raise InvalidPolicyError(f"SubLLM policy must configure exactly: {', '.join(_DEFAULTS)}")
    providers = {
        name: _validate_provider(name, provider_rows[name], source=source)
        for name in _DEFAULTS
    }
    application_rows = raw.get("applications")
    if isinstance(application_rows, dict):
        for app_name in ("organism-guard", "subactor-proxy", "premesh", "autogrammar-gillm"):
            if app_name not in application_rows and app_name in _APPLICATION_DEFAULTS:
                application_rows = {**application_rows, app_name: asdict(_APPLICATION_DEFAULTS[app_name])}
    if not isinstance(application_rows, dict) or set(application_rows) != set(APPLICATIONS):
        raise InvalidPolicyError(f"SubLLM policy must configure exactly these applications: {', '.join(APPLICATIONS)}")
    applications = {
        name: _validate_application(name, application_rows[name], source=source)
        for name in APPLICATIONS
    }
    custom_rows = raw.get("custom_providers", {})
    if not isinstance(custom_rows, dict):
        raise InvalidPolicyError(f"custom_providers must be a table in {source}")
    custom_providers = {
        name: _validate_custom_provider(name, custom_rows[name], source=source)
        for name in custom_rows
    }
    enabled_priorities = [settings.priority for settings in providers.values() if settings.enabled]
    enabled_priorities += [custom.priority for custom in custom_providers.values() if custom.enabled]
    if len(enabled_priorities) != len(set(enabled_priorities)):
        raise InvalidPolicyError(f"enabled providers must have unique priorities in {source}")
    execution = (
        _validate_execution(raw["execution"], source=source)
        if schema_version == 3
        else _EXECUTION_DEFAULTS
    )
    clear_custom_providers()
    for custom in custom_providers.values():
        spec = ProviderSpec(
            id=custom.id,
            api_base=custom.api_base,
            api_key_env=custom.api_key_env,
            transport="openai-compatible",
        )
        register_custom_provider(spec, custom.models)

    return RuntimePolicyConfig(
        providers=MappingProxyType(providers),
        applications=MappingProxyType(applications),
        execution=_execution_with_environment(execution, environ),
        custom_providers=MappingProxyType(custom_providers),
        source=source,
    )
