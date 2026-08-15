from __future__ import annotations

from types import MappingProxyType

from .types import (
    ApplicationSpec,
    ModelSpec,
    ProviderModelSpec,
    ProviderSpec,
    RouteCandidate,
    RoutePolicy,
)


def _provider_models(**values: ProviderModelSpec) -> MappingProxyType[str, ProviderModelSpec]:
    return MappingProxyType(values)


PROVIDERS = MappingProxyType(
    {
        "zai": ProviderSpec(
            id="zai",
            api_base="https://api.z.ai/api/coding/paas/v4",
            api_key_env="ZAI_API_KEY",
        ),
        "openrouter": ProviderSpec(
            id="openrouter",
            api_base="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            attribution_headers=True,
        ),
    }
)

# Shared .env names that are not LiteLLM routing providers. CURSOR_API_KEY is
# the name documented by the Cursor SDK (@cursor/sdk / cursor-sdk).
CURSOR_API_KEY_ENV = "CURSOR_API_KEY"
EXTRA_CREDENTIAL_ENV = (CURSOR_API_KEY_ENV,)

MODELS = MappingProxyType(
    {
        "glm-5.2": ModelSpec(
            id="glm-5.2",
            providers=_provider_models(
                zai=ProviderModelSpec(litellm_model="zai/glm-5.2", wire_model="glm-5.2"),
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/z-ai/glm-5.2",
                    wire_model="z-ai/glm-5.2",
                ),
            ),
        ),
        "grok-4.5": ModelSpec(
            id="grok-4.5",
            providers=_provider_models(
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/x-ai/grok-4.5",
                    wire_model="x-ai/grok-4.5",
                )
            ),
        ),
        "gemini-3.6-flash": ModelSpec(
            id="gemini-3.6-flash",
            providers=_provider_models(
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/google/gemini-3.6-flash",
                    wire_model="google/gemini-3.6-flash",
                )
            ),
        ),
        "deepseek-v4-pro": ModelSpec(
            id="deepseek-v4-pro",
            providers=_provider_models(
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/deepseek/deepseek-v4-pro",
                    wire_model="deepseek/deepseek-v4-pro",
                )
            ),
        ),
        "qwen3.7-plus": ModelSpec(
            id="qwen3.7-plus",
            providers=_provider_models(
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/qwen/qwen3.7-plus",
                    wire_model="qwen/qwen3.7-plus",
                )
            ),
        ),
        "gemini-3.1-pro-preview": ModelSpec(
            id="gemini-3.1-pro-preview",
            providers=_provider_models(
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/google/gemini-3.1-pro-preview",
                    wire_model="google/gemini-3.1-pro-preview",
                )
            ),
            forbidden=True,
        ),
    }
)

APPLICATIONS = MappingProxyType(
    {
        "doctor-agent": ApplicationSpec(
            id="doctor-agent",
            title="doctor-agent",
            url="https://github.com/subactor/doctor-agent",
        ),
        "repair-agent": ApplicationSpec(
            id="repair-agent",
            title="repair-agent",
            url="https://github.com/subactor/repair-agent",
        ),
        "validator-agent": ApplicationSpec(
            id="validator-agent",
            title="validator-agent",
            url="https://github.com/subactor/validator-agent",
        ),
        "skills-agent": ApplicationSpec(
            id="skills-agent",
            title="skills-agent",
            url="https://github.com/subactor/skills-agent",
        ),
        "onedev-agent": ApplicationSpec(
            id="onedev-agent",
            title="onedev-agent",
            url="https://github.com/subactor/onedev-agent",
        ),
        "todo2code": ApplicationSpec(
            id="todo2code",
            title="todo2code",
            url="https://github.com/semcod/todo2code",
        ),
        "platform": ApplicationSpec(
            id="platform",
            title="Subactor Platform",
            url="https://github.com/subactor/platform",
        ),
    }
)

_GLM = (
    RouteCandidate(provider="zai"),
    RouteCandidate(provider="openrouter"),
)

_ROUTE_VALUES = (
    RoutePolicy("doctor-agent", "repair-proposal", _GLM),
    RoutePolicy(
        "repair-agent",
        "repair-plan",
        _GLM + (RouteCandidate(provider="openrouter", model="deepseek-v4-pro", priority_offset=10),),
    ),
    RoutePolicy(
        "validator-agent",
        "patch-review",
        _GLM + (RouteCandidate(provider="openrouter", model="qwen3.7-plus", priority_offset=10),),
    ),
    RoutePolicy("validator-agent", "direct-pr-review", _GLM),
    RoutePolicy("skills-agent", "developer", _GLM),
    RoutePolicy("skills-agent", "validator", _GLM),
    RoutePolicy("onedev-agent", "code-edit", _GLM),
    RoutePolicy("todo2code", "semantic", _GLM),
    RoutePolicy(
        "platform",
        "interactive",
        _GLM
        + (
            RouteCandidate(provider="openrouter", model="grok-4.5", priority_offset=10),
            RouteCandidate(provider="openrouter", model="gemini-3.6-flash", priority_offset=20),
        ),
    ),
)

ROUTES = MappingProxyType({(route.application, route.function): route for route in _ROUTE_VALUES})
