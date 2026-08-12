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
class RuntimePolicyConfig:
    providers: Mapping[str, ProviderPolicyConfig]
    applications: Mapping[str, ApplicationPolicyConfig]
    source: Path | None = None


_DEFAULTS = MappingProxyType(
    {
        "zai": ProviderPolicyConfig(enabled=True, priority=10, default_model="glm-5.2"),
        "openrouter": ProviderPolicyConfig(enabled=True, priority=20, default_model="glm-5.2"),
    }
)

_APPLICATION_DEFAULTS = MappingProxyType(
    {
        name: ApplicationPolicyConfig(name=application.title, url=application.url)
        for name, application in APPLICATIONS.items()
    }
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


def load_policy_config(
    *,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> RuntimePolicyConfig:
    source = find_policy_file(environ=environ, cwd=cwd)
    if source is None:
        return RuntimePolicyConfig(providers=_DEFAULTS, applications=_APPLICATION_DEFAULTS)
    try:
        with source.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise InvalidPolicyError(f"SubLLM policy file does not exist: {source}") from exc
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise InvalidPolicyError(f"cannot read SubLLM policy file: {source}") from exc
    if set(raw) != {"schema_version", "providers", "applications"} or raw.get("schema_version") != 2:
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
        source=source,
    )
