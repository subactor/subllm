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


# Credential source → provider → transport. Cursor Sol is never an OpenRouter
# wire id. Catalog twin: wellmanifest/policy-dsl profiles/llm-credential and
# wellmanifest/env-dsl examples/valid/subllm-credential-strategies.env.
PROVIDERS = MappingProxyType(
    {
        "cursor": ProviderSpec(
            id="cursor",
            api_base="https://api.cursor.com",
            api_key_env="CURSOR_API_KEY",
            transport="cursor-sdk",
        ),
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

CURSOR_API_KEY_ENV = PROVIDERS["cursor"].api_key_env
EXTRA_CREDENTIAL_ENV: tuple[str, ...] = ()

# Comma-separated fallback chain. Unknown names fail closed.
SUBLLM_PROVIDER_ORDER = "SUBLLM_PROVIDER_ORDER"
ORDERABLE_PROVIDER_IDS = tuple(PROVIDERS)

MODELS = MappingProxyType(
    {
        "gpt-5.6-sol": ModelSpec(
            id="gpt-5.6-sol",
            providers=_provider_models(
                cursor=ProviderModelSpec(
                    litellm_model="cursor/gpt-5.6-sol",
                    wire_model="gpt-5.6-sol",
                )
            ),
        ),
        # Cursor SDK slug confirmed via Cursor.models.list(); not an OpenRouter wire id.
        "grok-4.6": ModelSpec(
            id="grok-4.6",
            providers=_provider_models(
                cursor=ProviderModelSpec(
                    litellm_model="cursor/grok-4.6",
                    wire_model="grok-4.6",
                )
            ),
        ),
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
        "glm-5.3": ModelSpec(
            id="glm-5.3",
            providers=_provider_models(
                zai=ProviderModelSpec(litellm_model="zai/glm-5.3", wire_model="glm-5.3"),
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
        "koru-agent": ApplicationSpec(
            id="koru-agent",
            title="Koru",
            url="https://github.com/semcod/koru",
        ),
        "platform": ApplicationSpec(
            id="platform",
            title="Subactor Platform",
            url="https://github.com/subactor/platform",
        ),
        "szeptnik-one": ApplicationSpec(
            id="szeptnik-one",
            title="Szeptnik One",
            url="https://github.com/tom-sapletta-com/watch",
        ),
        "supervisor": ApplicationSpec(
            id="supervisor",
            title="Subactor Supervisor",
            url="https://github.com/subactor/supervisor",
        ),
        "twinstudio": ApplicationSpec(
            id="twinstudio",
            title="TwinStudio",
            url="https://github.com/digitaltwin-run/twinstudio",
        ),
    }
)

# Prefer Cursor Sol, then Cursor Grok 4.6, when CURSOR_API_KEY is valid;
# otherwise Z.AI then OpenRouter. Both Cursor models use cursor-sdk transport.
_DEFAULT = (
    RouteCandidate(provider="cursor", model="gpt-5.6-sol"),
    RouteCandidate(provider="cursor", model="grok-4.6", priority_offset=5),
    RouteCandidate(provider="zai"),
    RouteCandidate(provider="openrouter"),
)

# Validator uses the direct Z.AI GLM-5.3 contract while retaining the existing
# OpenRouter GLM-5.2 fallback. Other applications remain on their current
# defaults until they are qualified independently.
_VALIDATOR = (
    RouteCandidate(provider="cursor", model="gpt-5.6-sol"),
    RouteCandidate(provider="cursor", model="grok-4.6", priority_offset=5),
    RouteCandidate(provider="zai", model="glm-5.3"),
    RouteCandidate(provider="openrouter", model="glm-5.2"),
)

# The watch desktop service currently invokes OpenAI-compatible Chat
# Completions directly. Cursor SDK candidates stay out of these two routes
# until that transport is implemented by the consumer.
_SZEPTNIK = (
    RouteCandidate(provider="zai"),
    RouteCandidate(provider="openrouter"),
)

# TwinStudio validates every answer locally. Keep Z.AI as the first choice,
# while retaining OpenRouter as a bounded fallback when a provider returns an
# empty or malformed completion.
_TWINSTUDIO_EDA = _SZEPTNIK

_ROUTE_VALUES = (
    RoutePolicy("doctor-agent", "repair-proposal", _DEFAULT),
    RoutePolicy(
        "repair-agent",
        "repair-plan",
        _DEFAULT + (RouteCandidate(provider="openrouter", model="deepseek-v4-pro", priority_offset=10),),
    ),
    RoutePolicy(
        "validator-agent",
        "patch-review",
        _VALIDATOR + (RouteCandidate(provider="openrouter", model="qwen3.7-plus", priority_offset=10),),
    ),
    RoutePolicy("validator-agent", "direct-pr-review", _VALIDATOR),
    RoutePolicy("skills-agent", "developer", _DEFAULT),
    RoutePolicy("skills-agent", "validator", _DEFAULT),
    RoutePolicy("onedev-agent", "code-edit", _DEFAULT),
    RoutePolicy("todo2code", "semantic", _DEFAULT),
    RoutePolicy("szeptnik-one", "program-generation", _SZEPTNIK),
    RoutePolicy("szeptnik-one", "voice-programming", _SZEPTNIK),
    RoutePolicy(
        "koru-agent",
        "planning-assistant",
        (
            RouteCandidate(
                provider="cursor",
                model="grok-4.6",
                model_parameters={"effort": "xhigh", "fast": "false"},
            ),
        ),
    ),
    RoutePolicy(
        "koru-agent",
        "queue-executor",
        (
            RouteCandidate(
                provider="cursor",
                model="grok-4.6",
                model_parameters={"effort": "xhigh", "fast": "false"},
            ),
        ),
    ),
    RoutePolicy(
        "platform",
        "interactive",
        _DEFAULT
        + (
            RouteCandidate(provider="openrouter", model="grok-4.5", priority_offset=10),
            RouteCandidate(provider="openrouter", model="gemini-3.6-flash", priority_offset=20),
        ),
    ),
    RoutePolicy(
        "platform",
        "site-audit",
        _DEFAULT
        + (
            RouteCandidate(provider="openrouter", model="grok-4.5", priority_offset=10),
            RouteCandidate(provider="openrouter", model="gemini-3.6-flash", priority_offset=20),
        ),
    ),
    RoutePolicy("supervisor", "assessment", _VALIDATOR),
    RoutePolicy("supervisor", "delegation", _VALIDATOR),
    RoutePolicy("supervisor", "review", _VALIDATOR),
    # TwinStudio currently consumes strict JSON Schema through LiteLLM. Keep
    # Cursor SDK candidates out until the consumer implements that transport.
    RoutePolicy("twinstudio", "eda-nl2dsl", _SZEPTNIK),
    RoutePolicy("twinstudio", "eda-firmware-audit", _TWINSTUDIO_EDA),
)

ROUTES = MappingProxyType({(route.application, route.function): route for route in _ROUTE_VALUES})
