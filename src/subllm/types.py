from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

Transport = Literal["openai-compatible", "cursor-sdk", "anthropic", "gemini-sdk"]
Modality = Literal["text", "vision"]


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
    vision: bool = False


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
    model_parameters: Mapping[str, str] = field(default_factory=dict, kw_only=True)


@dataclass(frozen=True)
class RoutePolicy:
    application: str
    function: str
    candidates: tuple[RouteCandidate, ...]
    modality: Modality = "text"


@dataclass(frozen=True)
class ConfiguredRoute:
    application: str
    application_name: str
    application_url: str
    function: str
    provider: str
    model: str
    priority: int
    api_base: str
    api_key_env: str
    litellm_model: str
    wire_model: str
    extra_headers: Mapping[str, str]
    transport: Transport
    model_parameters: Mapping[str, str] = field(default_factory=dict, kw_only=True)
    modality: Modality = field(default="text", kw_only=True)

    def public_dict(self) -> dict[str, Any]:
        return {
            "application": self.application,
            "application_name": self.application_name,
            "application_url": self.application_url,
            "function": self.function,
            "provider": self.provider,
            "model": self.model,
            "priority": self.priority,
            "api_base": self.api_base,
            "api_key_env": self.api_key_env,
            "litellm_model": self.litellm_model,
            "wire_model": self.wire_model,
            "extra_headers": dict(self.extra_headers),
            "transport": self.transport,
            "modality": self.modality,
            "model_parameters": dict(self.model_parameters),
        }

    def provider_request_fields(self, *, request_id: str | None = None) -> dict[str, str]:
        """Return non-secret application identity fields for one provider request."""
        if self.provider == "openrouter":
            return {"user": self.application}
        if self.provider == "zai":
            value = request_id or self._new_request_id()
            if not 6 <= len(value) <= 64:
                raise ValueError("Z.AI request_id must contain 6 to 64 characters")
            return {"request_id": value, "user_id": self.application}
        if self.provider == "cursor":
            return {"model": self.wire_model}
        return {}

    def litellm_attribution_kwargs(self) -> dict[str, Any]:
        """Return stable app attribution suitable for clients such as Aider."""
        if self.provider == "openrouter":
            return {
                "user": self.application,
                "extra_headers": dict(self.extra_headers),
            }
        if self.provider == "zai":
            return {"extra_body": {"user_id": self.application}}
        return {}

    def cursor_sdk_kwargs(self) -> dict[str, Any]:
        """Return non-secret fields for Cursor SDK Agent.create / Agent.prompt."""
        if self.transport != "cursor-sdk":
            raise ValueError(f"provider {self.provider} is not cursor-sdk transport")
        model: str | dict[str, Any] = self.wire_model
        if self.model_parameters:
            model = {
                "id": self.wire_model,
                "params": [
                    {"id": parameter, "value": value}
                    for parameter, value in self.model_parameters.items()
                ],
            }
        return {"model": model, "api_key_env": self.api_key_env}

    def _new_request_id(self) -> str:
        prefix = f"{self.application}-{self.function}"[:31].rstrip("-_")
        return f"{prefix}-{uuid4().hex}"


@dataclass(frozen=True)
class ResolvedRoute(ConfiguredRoute):
    api_key: str = field(repr=False)

    def litellm_kwargs(self, *, request_id: str | None = None) -> dict[str, Any]:
        if self.transport == "cursor-sdk":
            raise ValueError(
                "provider cursor uses Cursor SDK transport; call cursor_sdk_kwargs() "
                "and pass wire_model with CURSOR_API_KEY — not LiteLLM / OpenRouter"
            )
        result: dict[str, Any] = {
            "model": self.litellm_model,
            "api_key": self.api_key,
            "api_base": self.api_base,
        }
        if self.extra_headers:
            result["extra_headers"] = dict(self.extra_headers)
        fields = self.provider_request_fields(request_id=request_id)
        if self.provider == "zai":
            result["extra_body"] = fields
        else:
            result.update(fields)
        return result

    def cursor_sdk_kwargs(self) -> dict[str, Any]:
        fields = super().cursor_sdk_kwargs()
        return {**fields, "api_key": self.api_key}
