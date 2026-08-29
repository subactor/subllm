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
ORDERABLE_PROVIDER_IDS = ("zai", "cursor", "openrouter")

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
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/z-ai/glm-5.3",
                    wire_model="z-ai/glm-5.3",
                ),
            ),
        ),
        "glm-5.3-flash": ModelSpec(
            id="glm-5.3-flash",
            providers=_provider_models(
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/z-ai/glm-5.3-flash",
                    wire_model="z-ai/glm-5.3-flash",
                ),
            ),
        ),
        "glm-4.5v": ModelSpec(
            id="glm-4.5v",
            vision=True,
            providers=_provider_models(
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/z-ai/glm-4.5v",
                    wire_model="z-ai/glm-4.5v",
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
            vision=True,
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
            url="https://github.com/autogrammar/todo2code",
        ),
        "koru-agent": ApplicationSpec(
            id="koru-agent",
            title="Koru",
            url="https://github.com/semcod/koru",
        ),
        "c2004-system": ApplicationSpec(
            id="c2004-system",
            title="C2004",
            url="https://github.com/maskservice/c2004",
        ),
        "prellm": ApplicationSpec(
            id="prellm",
            title="PreLLM",
            url="https://github.com/semcod/prellm",
        ),
        "semcod-nfo": ApplicationSpec(
            id="semcod-nfo",
            title="NFO",
            url="https://github.com/semcod/nfo",
        ),
        "semcod-code2logic": ApplicationSpec(
            id="semcod-code2logic", title="code2logic", url="https://github.com/semcod/code2logic"
        ),
        "semcod-code2docs": ApplicationSpec(
            id="semcod-code2docs", title="code2docs", url="https://github.com/semcod/code2docs"
        ),
        "semcod-vallm": ApplicationSpec(
            id="semcod-vallm", title="vallm", url="https://github.com/semcod/vallm"
        ),
        "semcod-taskill": ApplicationSpec(
            id="semcod-taskill", title="taskill", url="https://github.com/semcod/taskill"
        ),
        "semcod-fixos": ApplicationSpec(
            id="semcod-fixos", title="fixos", url="https://github.com/semcod/fixos"
        ),
        "semcod-pfix": ApplicationSpec(
            id="semcod-pfix", title="pfix", url="https://github.com/semcod/pfix"
        ),
        "semcod-algitex": ApplicationSpec(
            id="semcod-algitex", title="algitex", url="https://github.com/semcod/algitex"
        ),
        "semcod-docval": ApplicationSpec(
            id="semcod-docval", title="docval", url="https://github.com/semcod/docval"
        ),
        "semcod-planfile": ApplicationSpec(
            id="semcod-planfile", title="planfile", url="https://github.com/semcod/planfile"
        ),
        "autogrammar-nexu": ApplicationSpec(
            id="autogrammar-nexu", title="nexu", url="https://github.com/autogrammar/nexu"
        ),
        "autogrammar-intract": ApplicationSpec(
            id="autogrammar-intract", title="intract", url="https://github.com/autogrammar/intract"
        ),
        "autogrammar-nlp2cmd": ApplicationSpec(
            id="autogrammar-nlp2cmd", title="nlp2cmd", url="https://github.com/autogrammar/nlp2cmd"
        ),
        "autogrammar-nlp2dsl": ApplicationSpec(
            id="autogrammar-nlp2dsl", title="nlp2dsl", url="https://github.com/autogrammar/nlp2dsl"
        ),
        "autogrammar-imgl": ApplicationSpec(
            id="autogrammar-imgl", title="imgl", url="https://github.com/autogrammar/imgl"
        ),
        "autogrammar-tillm": ApplicationSpec(
            id="autogrammar-tillm", title="tillm", url="https://github.com/autogrammar/tillm"
        ),
        "autogrammar-hillm": ApplicationSpec(
            id="autogrammar-hillm", title="hillm", url="https://github.com/autogrammar/hillm"
        ),
        "autogrammar-doql": ApplicationSpec(
            id="autogrammar-doql", title="doql", url="https://github.com/autogrammar/doql"
        ),
        "autogrammar-toonic": ApplicationSpec(
            id="autogrammar-toonic", title="toonic", url="https://github.com/autogrammar/toonic"
        ),
        "autogrammar-curllm": ApplicationSpec(
            id="autogrammar-curllm", title="curllm", url="https://github.com/autogrammar/curllm"
        ),
        "autogrammar-testql": ApplicationSpec(
            id="autogrammar-testql", title="testql", url="https://github.com/autogrammar/testql"
        ),
        "autogrammar-redsl": ApplicationSpec(
            id="autogrammar-redsl", title="redsl", url="https://github.com/autogrammar/redsl"
        ),
        "autogrammar-vql": ApplicationSpec(
            id="autogrammar-vql", title="vql", url="https://github.com/autogrammar/vql"
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
    }
)

# Prefer direct Z.AI GLM 5.3 for every registered LLM route. Cursor and
# OpenRouter remain pre-request fallbacks selected only when the preferred
# credential is unavailable or an operator explicitly overrides provider order.
_DEFAULT = (
    RouteCandidate(provider="zai", model="glm-5.3"),
    RouteCandidate(provider="cursor", model="gpt-5.6-sol"),
    RouteCandidate(provider="cursor", model="grok-4.6", priority_offset=5),
    RouteCandidate(provider="openrouter"),
)

# Role-specific OpenRouter fallbacks are selected from the current benchmark:
# full GLM 5.3 for repair structured JSON, full GLM 5.3 for review and coding.
_REPAIR = (
    RouteCandidate(provider="zai", model="glm-5.3"),
    RouteCandidate(provider="cursor", model="gpt-5.6-sol"),
    RouteCandidate(provider="cursor", model="grok-4.6", priority_offset=5),
    RouteCandidate(provider="openrouter", model="glm-5.3"),
)

_VALIDATOR = (
    RouteCandidate(provider="zai", model="glm-5.3"),
    RouteCandidate(provider="cursor", model="gpt-5.6-sol"),
    RouteCandidate(provider="cursor", model="grok-4.6", priority_offset=5),
    RouteCandidate(provider="openrouter", model="glm-5.3"),
)

_CODING = (
    RouteCandidate(provider="zai", model="glm-5.3"),
    RouteCandidate(provider="cursor", model="gpt-5.6-sol"),
    RouteCandidate(provider="cursor", model="grok-4.6", priority_offset=5),
    RouteCandidate(provider="openrouter", model="glm-5.3"),
)

# Vision routes stay on OpenAI-compatible transports. Cursor SDK is text-only
# and is never a vision candidate. Z.AI coding GLM 5.3 is not marked vision.
_VISION = (
    RouteCandidate(provider="openrouter", model="glm-4.5v"),
    RouteCandidate(provider="openrouter", model="gemini-3.6-flash", priority_offset=10),
)

# The watch desktop service currently invokes OpenAI-compatible Chat
# Completions directly. Cursor SDK candidates stay out of these two routes
# until that transport is implemented by the consumer.
_SZEPTNIK = (
    RouteCandidate(provider="zai", model="glm-5.3"),
    RouteCandidate(provider="openrouter", model="glm-5.2"),
)

_ROUTE_VALUES = (
    RoutePolicy("doctor-agent", "repair-proposal", _DEFAULT),
    RoutePolicy("repair-agent", "repair-plan", _REPAIR),
    RoutePolicy(
        "validator-agent",
        "patch-review",
        _VALIDATOR + (RouteCandidate(provider="openrouter", model="qwen3.7-plus", priority_offset=10),),
    ),
    RoutePolicy("validator-agent", "direct-pr-review", _VALIDATOR),
    RoutePolicy("skills-agent", "developer", _DEFAULT),
    RoutePolicy("skills-agent", "process-editor", _DEFAULT),
    RoutePolicy("skills-agent", "validator", _DEFAULT),
    # Host coding-agent invokes this canonical route through subllm-code-edit.
    RoutePolicy("onedev-agent", "code-edit", _CODING),
    RoutePolicy("todo2code", "semantic", _DEFAULT),
    RoutePolicy("szeptnik-one", "program-generation", _SZEPTNIK),
    RoutePolicy("szeptnik-one", "voice-programming", _SZEPTNIK),
    RoutePolicy(
        "koru-agent",
        "planning-assistant",
        _DEFAULT,
    ),
    RoutePolicy(
        "koru-agent",
        "queue-executor",
        _DEFAULT,
    ),
    RoutePolicy(
        "koru-agent",
        "reflection",
        _DEFAULT,
    ),
    RoutePolicy("koru-agent", "nl-to-koru-dsl", _DEFAULT),
    RoutePolicy("koru-agent", "nl-to-coru-dsl", _DEFAULT),
    RoutePolicy("koru-agent", "strategy-review", _DEFAULT),
    RoutePolicy("c2004-system", "oql-generation", _DEFAULT),
    RoutePolicy("c2004-system", "doctor-recommendation", _DEFAULT),
    RoutePolicy("prellm", "preprocess", _DEFAULT),
    RoutePolicy("prellm", "execute", _DEFAULT),
    RoutePolicy("semcod-nfo", "analyze", _DEFAULT),
    RoutePolicy("semcod-code2logic", "analyze", _DEFAULT),
    RoutePolicy("semcod-code2docs", "generate", _DEFAULT),
    RoutePolicy("semcod-vallm", "invoke", _DEFAULT),
    RoutePolicy("semcod-taskill", "execute", _DEFAULT),
    RoutePolicy("semcod-fixos", "repair", _DEFAULT),
    RoutePolicy("semcod-pfix", "repair", _DEFAULT),
    RoutePolicy("semcod-algitex", "autofix", _DEFAULT),
    RoutePolicy("semcod-docval", "validate", _DEFAULT),
    RoutePolicy("semcod-planfile", "plan", _DEFAULT),
    RoutePolicy("autogrammar-nexu", "generate", _DEFAULT),
    RoutePolicy("autogrammar-nexu", "cinema", _DEFAULT),
    RoutePolicy("autogrammar-nexu", "vision", _VISION, modality="vision"),
    RoutePolicy("autogrammar-intract", "propose", _DEFAULT),
    RoutePolicy("autogrammar-nlp2cmd", "generate", _DEFAULT),
    RoutePolicy("autogrammar-nlp2cmd", "extract-schema", _DEFAULT),
    RoutePolicy("autogrammar-nlp2cmd", "vision", _VISION, modality="vision"),
    RoutePolicy("autogrammar-nlp2dsl", "generate", _DEFAULT),
    RoutePolicy("autogrammar-imgl", "generate", _DEFAULT),
    RoutePolicy("autogrammar-imgl", "vision", _VISION, modality="vision"),
    RoutePolicy("autogrammar-tillm", "invoke", _DEFAULT),
    RoutePolicy("autogrammar-hillm", "invoke", _DEFAULT),
    RoutePolicy("autogrammar-doql", "translate", _DEFAULT),
    RoutePolicy("autogrammar-toonic", "invoke", _DEFAULT),
    RoutePolicy("autogrammar-curllm", "invoke", _DEFAULT),
    RoutePolicy("autogrammar-testql", "generate", _DEFAULT),
    RoutePolicy("autogrammar-redsl", "evaluate", _DEFAULT),
    RoutePolicy("autogrammar-vql", "generate", _DEFAULT),
    RoutePolicy("autogrammar-vql", "vision", _VISION, modality="vision"),
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
    RoutePolicy("supervisor", "assessment", _DEFAULT),
    RoutePolicy("supervisor", "delegation", _DEFAULT),
    RoutePolicy("supervisor", "review", _DEFAULT),
)

ROUTES = MappingProxyType({(route.application, route.function): route for route in _ROUTE_VALUES})
