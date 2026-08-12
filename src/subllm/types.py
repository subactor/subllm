from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

Transport = Literal["openai-compatible"]


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    api_base: str
    api_key_env: str
    transport: Transport = "openai-compatible"
    attribution_headers: bool = False


@dataclass(frozen=True)
class ProviderModelSpec:
    litellm_model: str
    wire_model: str


@dataclass(frozen=True)
class ModelSpec:
    id: str
    providers: Mapping[str, ProviderModelSpec]
    forbidden: bool = False


@dataclass(frozen=True)
class ApplicationSpec:
    id: str
    title: str
    url: str


@dataclass(frozen=True)
class RouteCandidate:
    provider: str
    model: str | None = None
    priority_offset: int = 0


@dataclass(frozen=True)
class RoutePolicy:
    application: str
    function: str
    candidates: tuple[RouteCandidate, ...]


@dataclass(frozen=True)
class ConfiguredRoute:
    application: str
    function: str
    provider: str
    model: str
    priority: int
    api_base: str
    api_key_env: str
    litellm_model: str
    wire_model: str
    extra_headers: Mapping[str, str]

    def public_dict(self) -> dict[str, Any]:
        return {
            "application": self.application,
            "function": self.function,
            "provider": self.provider,
            "model": self.model,
            "priority": self.priority,
            "api_base": self.api_base,
            "api_key_env": self.api_key_env,
            "litellm_model": self.litellm_model,
            "wire_model": self.wire_model,
            "extra_headers": dict(self.extra_headers),
        }


@dataclass(frozen=True)
class ResolvedRoute(ConfiguredRoute):
    api_key: str = field(repr=False)

    def litellm_kwargs(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "model": self.litellm_model,
            "api_key": self.api_key,
            "api_base": self.api_base,
        }
        if self.extra_headers:
            result["extra_headers"] = dict(self.extra_headers)
        return result
