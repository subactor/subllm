from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
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
_BASE_PROVIDERS = MappingProxyType(
    {
        "zai": ProviderSpec(
            id="zai",
            api_base="https://api.z.ai/api/coding/paas/v4",
            api_key_env="ZAI_API_KEY",
        ),
        "agy": ProviderSpec(
            id="agy",
            api_base="https://generativelanguage.googleapis.com/v1beta",
            api_key_env="GEMINI_API_KEY",
            transport="gemini-sdk",
        ),
        "codex-cli": ProviderSpec(
            id="codex-cli", api_base="", api_key_env="", transport="codex-cli",
        ),
        "claude-cli": ProviderSpec(
            id="claude-cli", api_base="", api_key_env="", transport="claude-cli",
        ),
        "agy-cli": ProviderSpec(
            id="agy-cli", api_base="", api_key_env="", transport="agy-cli",
        ),
        "codex": ProviderSpec(
            id="codex",
            api_base="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            transport="openai-compatible",
        ),
        "claude": ProviderSpec(
            id="claude",
            api_base="https://api.anthropic.com/v1",
            api_key_env="ANTHROPIC_API_KEY",
            transport="anthropic",
        ),
        "cursor": ProviderSpec(
            id="cursor",
            api_base="https://api.cursor.com",
            api_key_env="CURSOR_API_KEY",
            transport="cursor-sdk",
        ),
        "ollama": ProviderSpec(
            id="ollama",
            api_base="http://127.0.0.1:11434/v1",
            api_key_env="OLLAMA_API_KEY",
            transport="openai-compatible",
        ),
        "openrouter": ProviderSpec(
            id="openrouter",
            api_base="https://openrouter.ai/api/v1",
            api_key_env="OPENROUTER_API_KEY",
            attribution_headers=True,
        ),
    }
)

_BASE_ORDERABLE_PROVIDER_IDS = (
    "zai", "agy", "codex", "claude", "cursor", "ollama", "openrouter", "codex-cli", "claude-cli", "agy-cli",
)

_BASE_MODELS = MappingProxyType(
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
        "z-ai/glm-5.3": ModelSpec(
            id="z-ai/glm-5.3",
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
                zai=ProviderModelSpec(litellm_model="zai/glm-5.3-flash", wire_model="glm-5.3-flash"),
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
                agy=ProviderModelSpec(
                    litellm_model="gemini/gemini-3.6-flash",
                    wire_model="gemini-3.6-flash",
                ),
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/google/gemini-3.6-flash",
                    wire_model="google/gemini-3.6-flash",
                ),
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
        "gemini-3.1-pro-high": ModelSpec(
            id="gemini-3.1-pro-high",
            providers=_provider_models(
                **{"agy-cli": ProviderModelSpec(litellm_model="", wire_model="gemini-3.1-pro-high")},
                agy=ProviderModelSpec(
                    litellm_model="gemini/gemini-3.1-pro-preview",
                    wire_model="gemini-3.1-pro-preview",
                ),
            ),
        ),
        "gemini-3.7-flash-medium": ModelSpec(
            id="gemini-3.7-flash-medium",
            providers=_provider_models(
                **{"agy-cli": ProviderModelSpec(litellm_model="", wire_model="gemini-3.7-flash-medium")},
                agy=ProviderModelSpec(
                    litellm_model="gemini/gemini-3.7-flash",
                    wire_model="gemini-3.7-flash",
                ),
            ),
        ),
        # Gemini API models available to new AI Studio keys (verified 2026-09-20). The free tier has no Pro quota.
        "gemini-3.8-flash": ModelSpec(
            id="gemini-3.8-flash",
            providers=_provider_models(
                **{"agy-cli": ProviderModelSpec(litellm_model="", wire_model="gemini-3.8-flash-medium")},
                agy=ProviderModelSpec(
                    litellm_model="gemini/gemini-3.8-flash",
                    wire_model="gemini-3.8-flash",
                ),
            ),
        ),
        "gemini-3.5-flash-lite": ModelSpec(
            id="gemini-3.5-flash-lite",
            providers=_provider_models(
                agy=ProviderModelSpec(
                    litellm_model="gemini/gemini-3.5-flash-lite",
                    wire_model="gemini-3.5-flash-lite",
                ),
            ),
        ),
        "claude-opus-5": ModelSpec(
            id="claude-opus-5",
            providers=_provider_models(
                **{"claude-cli": ProviderModelSpec(litellm_model="", wire_model="claude-opus-5")},
                claude=ProviderModelSpec(
                    litellm_model="anthropic/claude-opus-5",
                    wire_model="claude-opus-5",
                ),
            ),
        ),
        "claude-sonnet-5": ModelSpec(
            id="claude-sonnet-5",
            providers=_provider_models(
                **{"claude-cli": ProviderModelSpec(litellm_model="", wire_model="claude-sonnet-5")},
                claude=ProviderModelSpec(
                    litellm_model="anthropic/claude-sonnet-5",
                    wire_model="claude-sonnet-5",
                ),
            ),
        ),
        # Claude models Antigravity serves through its own login (no Anthropic key).
        "claude-sonnet-4-6": ModelSpec(
            id="claude-sonnet-4-6",
            providers=_provider_models(
                **{"agy-cli": ProviderModelSpec(litellm_model="", wire_model="claude-sonnet-4-6")},
            ),
        ),
        "claude-opus-4-6-thinking": ModelSpec(
            id="claude-opus-4-6-thinking",
            providers=_provider_models(
                **{"agy-cli": ProviderModelSpec(litellm_model="", wire_model="claude-opus-4-6-thinking")},
            ),
        ),
        "gpt-5.6-sol": ModelSpec(
            id="gpt-5.6-sol",
            providers=_provider_models(
                **{"codex-cli": ProviderModelSpec(litellm_model="", wire_model="gpt-5.6-sol")},
                codex=ProviderModelSpec(
                    litellm_model="openai/gpt-5.6-sol",
                    wire_model="gpt-5.6-sol",
                ),
                cursor=ProviderModelSpec(
                    litellm_model="cursor/gpt-5.6-sol",
                    wire_model="gpt-5.6-sol",
                ),
            ),
        ),
        "gpt-5.6-terra": ModelSpec(
            id="gpt-5.6-terra",
            providers=_provider_models(
                codex=ProviderModelSpec(
                    litellm_model="openai/gpt-5.6-terra",
                    wire_model="gpt-5.6-terra",
                ),
            ),
        ),
        "gpt-5.6-luna": ModelSpec(
            id="gpt-5.6-luna",
            providers=_provider_models(
                **{"codex-cli": ProviderModelSpec(litellm_model="", wire_model="gpt-5.6-luna")},
                codex=ProviderModelSpec(
                    litellm_model="openai/gpt-5.6-luna",
                    wire_model="gpt-5.6-luna",
                ),
            ),
        ),
        "qwen3-coder:30b": ModelSpec(
            id="qwen3-coder:30b",
            providers=_provider_models(
                ollama=ProviderModelSpec(
                    litellm_model="ollama/qwen3-coder:30b",
                    wire_model="qwen3-coder:30b",
                ),
            ),
        ),
        "grok-4.6": ModelSpec(
            id="grok-4.6",
            providers=_provider_models(
                cursor=ProviderModelSpec(
                    litellm_model="cursor/grok-4.6",
                    wire_model="grok-4.6",
                ),
            ),
        ),
        "composer-2.5": ModelSpec(
            id="composer-2.5",
            providers=_provider_models(
                cursor=ProviderModelSpec(
                    litellm_model="cursor/composer-2.5",
                    wire_model="composer-2.5",
                ),
            ),
        ),
        "gemini-2.5-flash": ModelSpec(
            id="gemini-2.5-flash",
            providers=_provider_models(
                agy=ProviderModelSpec(
                    litellm_model="gemini/gemini-2.5-flash",
                    wire_model="gemini-2.5-flash",
                ),
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/google/gemini-2.5-flash",
                    wire_model="google/gemini-2.5-flash",
                ),
            ),
        ),
        "gemini-2.5-pro": ModelSpec(
            id="gemini-2.5-pro",
            providers=_provider_models(
                agy=ProviderModelSpec(
                    litellm_model="gemini/gemini-2.5-pro",
                    wire_model="gemini-2.5-pro",
                ),
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/google/gemini-2.5-pro",
                    wire_model="google/gemini-2.5-pro",
                ),
            ),
        ),
        "gpt-5.5": ModelSpec(
            id="gpt-5.5",
            providers=_provider_models(
                codex=ProviderModelSpec(
                    litellm_model="openai/gpt-5.5",
                    wire_model="gpt-5.5",
                ),
                cursor=ProviderModelSpec(
                    litellm_model="cursor/gpt-5.5",
                    wire_model="gpt-5.5",
                ),
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/openai/gpt-5.5",
                    wire_model="openai/gpt-5.5",
                ),
            ),
        ),
        "claude-3.7-sonnet": ModelSpec(
            id="claude-3.7-sonnet",
            providers=_provider_models(
                claude=ProviderModelSpec(
                    litellm_model="anthropic/claude-3-7-sonnet-20250219",
                    wire_model="claude-3-7-sonnet-20250219",
                ),
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/anthropic/claude-3.7-sonnet",
                    wire_model="anthropic/claude-3.7-sonnet",
                ),
            ),
        ),
        "qwen2.5-coder": ModelSpec(
            id="qwen2.5-coder",
            providers=_provider_models(
                ollama=ProviderModelSpec(
                    litellm_model="ollama/qwen2.5-coder",
                    wire_model="qwen2.5-coder",
                ),
                openrouter=ProviderModelSpec(
                    litellm_model="openrouter/qwen/qwen-2.5-coder-32b-instruct",
                    wire_model="qwen/qwen-2.5-coder-32b-instruct",
                ),
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


class _ProvidersCatalog(Mapping[str, ProviderSpec]):
    def __init__(self, base: Mapping[str, ProviderSpec]) -> None:
        self._base = base
        self._custom: dict[str, ProviderSpec] = {}

    def register_custom(self, provider_spec: ProviderSpec) -> None:
        self._custom[provider_spec.id] = provider_spec

    def clear_custom(self) -> None:
        self._custom.clear()

    def __getitem__(self, key: str) -> ProviderSpec:
        if key in self._custom:
            return self._custom[key]
        return self._base[key]

    def __iter__(self) -> Iterator[str]:
        yield from self._base
        for k in self._custom:
            if k not in self._base:
                yield k

    def __len__(self) -> int:
        return len(set(self._base) | set(self._custom))

    def __contains__(self, key: object) -> bool:
        return key in self._custom or key in self._base

    def get(self, key: str, default: ProviderSpec | None = None) -> ProviderSpec | None:
        if key in self._custom:
            return self._custom[key]
        return self._base.get(key, default)


class _ModelsCatalog(Mapping[str, ModelSpec]):
    def __init__(self, base: Mapping[str, ModelSpec]) -> None:
        self._base = base
        self._custom: dict[str, ModelSpec] = {}

    def register_custom(self, model_spec: ModelSpec) -> None:
        if model_spec.id in self._base:
            base_model = self._base[model_spec.id]
            merged_providers = {**base_model.providers, **model_spec.providers}
            self._custom[model_spec.id] = replace(base_model, providers=MappingProxyType(merged_providers))
        elif model_spec.id in self._custom:
            existing = self._custom[model_spec.id]
            merged_providers = {**existing.providers, **model_spec.providers}
            self._custom[model_spec.id] = replace(existing, providers=MappingProxyType(merged_providers))
        else:
            self._custom[model_spec.id] = model_spec

    def clear_custom(self) -> None:
        self._custom.clear()

    def __getitem__(self, key: str) -> ModelSpec:
        if key in self._custom:
            return self._custom[key]
        return self._base[key]

    def __iter__(self) -> Iterator[str]:
        yield from self._base
        for k in self._custom:
            if k not in self._base:
                yield k

    def __len__(self) -> int:
        return len(set(self._base) | set(self._custom))

    def __contains__(self, key: object) -> bool:
        return key in self._custom or key in self._base

    def get(self, key: str, default: ModelSpec | None = None) -> ModelSpec | None:
        if key in self._custom:
            return self._custom[key]
        return self._base.get(key, default)


class _OrderableProviderIds(Sequence[str]):
    def __init__(self, base: tuple[str, ...], catalog: _ProvidersCatalog) -> None:
        self._base = base
        self._catalog = catalog

    def _all(self) -> tuple[str, ...]:
        custom_ids = tuple(k for k in self._catalog._custom if k not in self._base)
        return self._base + custom_ids

    def __getitem__(self, index: int | slice) -> str | Sequence[str]:
        return self._all()[index]

    def __len__(self) -> int:
        return len(self._all())

    def __contains__(self, item: object) -> bool:
        return item in self._base or item in self._catalog._custom

    def __iter__(self) -> Iterator[str]:
        return iter(self._all())

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (tuple, list)):
            return self._all() == tuple(other)
        if isinstance(other, _OrderableProviderIds):
            return self._all() == other._all()
        return False

    def __repr__(self) -> str:
        return repr(self._all())


PROVIDERS = _ProvidersCatalog(_BASE_PROVIDERS)
CURSOR_API_KEY_ENV = PROVIDERS["cursor"].api_key_env
EXTRA_CREDENTIAL_ENV: tuple[str, ...] = ()
SUBLLM_PROVIDER_ORDER = "SUBLLM_PROVIDER_ORDER"
ORDERABLE_PROVIDER_IDS = _OrderableProviderIds(_BASE_ORDERABLE_PROVIDER_IDS, PROVIDERS)
MODELS = _ModelsCatalog(_BASE_MODELS)


def register_custom_provider(spec: ProviderSpec, models: tuple[str, ...] = ()) -> None:
    PROVIDERS.register_custom(spec)
    for model_name in models:
        model_spec = ModelSpec(
            id=model_name,
            providers=MappingProxyType(
                {
                    spec.id: ProviderModelSpec(
                        litellm_model=f"openai/{model_name}",
                        wire_model=model_name,
                    )
                }
            ),
        )
        MODELS.register_custom(model_spec)


def clear_custom_providers() -> None:
    PROVIDERS.clear_custom()
    MODELS.clear_custom()


APPLICATIONS = MappingProxyType(
    {
        "organism-guard": ApplicationSpec(
            id="organism-guard", title="Organism Guard",
            url="https://github.com/subactor/organism-guard",
        ),
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
        "twinstudio": ApplicationSpec(
            id="twinstudio",
            title="TwinStudio",
            url="https://github.com/subactor/twinstudio",
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
        "subactor-proxy": ApplicationSpec(
            id="subactor-proxy",
            title="Subactor Proxy",
            url="https://github.com/subactor/subllm",
        ),
        "premesh": ApplicationSpec(
            id="premesh",
            title="Premesh",
            url="https://github.com/subactor/premesh",
        ),
        "autogrammar-gillm": ApplicationSpec(
            id="autogrammar-gillm",
            title="gillm",
            url="https://github.com/autogrammar/gillm",
        ),
    }
)

# Prefer direct Z.AI GLM 5.3 for every registered LLM route. Cursor and
# OpenRouter remain declared fallbacks. The runtime executor may advance only
# through this exact list after a bounded retryable attempt failure.
_DEFAULT = (
    RouteCandidate(provider="zai", model="glm-5.3"),
    RouteCandidate(provider="cursor", model="gpt-5.6-sol"),
    RouteCandidate(provider="cursor", model="grok-4.6", priority_offset=5),
    RouteCandidate(provider="agy", model="gemini-3.8-flash"),
    RouteCandidate(provider="agy", model="gemini-3.6-flash", priority_offset=1),
    RouteCandidate(provider="codex", model="gpt-5.6-sol"),
    RouteCandidate(provider="claude", model="claude-sonnet-5"),
    RouteCandidate(provider="ollama", model="qwen3-coder:30b", priority_offset=1),
    RouteCandidate(provider="agy-cli", model="claude-sonnet-4-6"),
    RouteCandidate(provider="claude-cli", model="claude-sonnet-5"),
    RouteCandidate(provider="openrouter"),
)

# Periodic assessment is bounded triage; GLM-5.3 defaults to max effort.
# Preserve the shared candidates and other routes, changing only this role's
# direct ZAI parameter. Planning, coding and repair retain their defaults.
_SUPERVISOR_ASSESSMENT = tuple(
    replace(candidate, model_parameters=MappingProxyType({"reasoning_effort": "low"}))
    if candidate.provider == "zai" else candidate
    for candidate in _DEFAULT
)

# Role-specific OpenRouter fallbacks are selected from the current benchmark:
# GLM 5.3 for repair structured JSON; GLM 5.3 Flash for validator review.
_REPAIR = (
    RouteCandidate(provider="zai", model="glm-5.3"),
    RouteCandidate(provider="cursor", model="gpt-5.6-sol"),
    RouteCandidate(provider="cursor", model="grok-4.6", priority_offset=5),
    RouteCandidate(provider="agy", model="gemini-3.8-flash"),
    RouteCandidate(provider="agy", model="gemini-3.6-flash", priority_offset=1),
    RouteCandidate(provider="codex", model="gpt-5.6-sol"),
    RouteCandidate(provider="claude", model="claude-sonnet-5"),
    RouteCandidate(provider="ollama", model="qwen3-coder:30b", priority_offset=1),
    RouteCandidate(provider="agy-cli", model="claude-sonnet-4-6"),
    RouteCandidate(provider="claude-cli", model="claude-sonnet-5"),
    RouteCandidate(provider="openrouter", model="glm-5.3"),
)

_VALIDATOR = (
    RouteCandidate(provider="zai", model="glm-5.3"),
    RouteCandidate(provider="cursor", model="gpt-5.6-sol"),
    RouteCandidate(provider="cursor", model="grok-4.6", priority_offset=5),
    RouteCandidate(provider="agy", model="gemini-3.8-flash"),
    RouteCandidate(provider="agy", model="gemini-3.6-flash", priority_offset=1),
    RouteCandidate(provider="codex", model="gpt-5.6-sol"),
    RouteCandidate(provider="claude", model="claude-sonnet-5"),
    RouteCandidate(provider="ollama", model="qwen3-coder:30b", priority_offset=1),
    RouteCandidate(provider="agy-cli", model="claude-sonnet-4-6"),
    RouteCandidate(provider="claude-cli", model="claude-sonnet-5"),
    RouteCandidate(provider="openrouter", model="glm-5.3-flash"),
)

# Koru autonomous work lost runs when the three shared lanes all failed in the
# same window (zai rate-limit, cursor unavailable, OpenRouter GLM timeout).
# deepseek-v4-pro is catalogued on the OpenRouter lane already; appending it as
# a strictly-later candidate keeps the shared order intact and gives koru-agent
# routes one more declared model before the executor gives up.
_KORU = _DEFAULT + (
    RouteCandidate(provider="openrouter", model="deepseek-v4-pro", priority_offset=30),
)

_CODING = (
    RouteCandidate(provider="zai", model="glm-5.3"),
    RouteCandidate(provider="cursor", model="gpt-5.6-sol"),
    RouteCandidate(provider="cursor", model="grok-4.6", priority_offset=5),
    RouteCandidate(provider="agy", model="gemini-3.8-flash"),
    RouteCandidate(provider="agy", model="gemini-3.6-flash", priority_offset=1),
    RouteCandidate(provider="codex", model="gpt-5.6-sol"),
    RouteCandidate(provider="claude", model="claude-sonnet-5"),
    RouteCandidate(provider="ollama", model="qwen3-coder:30b", priority_offset=1),
    RouteCandidate(provider="agy-cli", model="claude-sonnet-4-6"),
    RouteCandidate(provider="claude-cli", model="claude-sonnet-5"),
    RouteCandidate(provider="openrouter", model="glm-5.3"),
)

# Semantic evidence selection is a bounded ID query, separate from code editing.
# Keep the same provider membership; the OpenRouter selection role uses Flash.
_CODE_CONTEXT = tuple(
    replace(candidate, model="glm-5.3-flash", model_parameters=MappingProxyType({"reasoning_effort": "low"}))
    if candidate.provider == "openrouter" else candidate
    for candidate in _CODING
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
    RoutePolicy("organism-guard", "refactor", (RouteCandidate(provider="codex-cli"),)),
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
    RoutePolicy("onedev-agent", "code-context", _CODE_CONTEXT),
    RoutePolicy("todo2code", "semantic", _DEFAULT),
    RoutePolicy("szeptnik-one", "program-generation", _SZEPTNIK),
    RoutePolicy("szeptnik-one", "voice-programming", _SZEPTNIK),
    RoutePolicy(
        "koru-agent",
        "planning-assistant",
        _KORU,
    ),
    RoutePolicy(
        "koru-agent",
        "queue-executor",
        _KORU,
    ),
    RoutePolicy(
        "koru-agent",
        "reflection",
        _KORU,
    ),
    RoutePolicy("koru-agent", "nl-to-koru-dsl", _KORU),
    RoutePolicy("koru-agent", "nl-to-coru-dsl", _KORU),
    RoutePolicy("koru-agent", "strategy-review", _KORU),
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
    # TwinStudio keeps the EDA output schema and candidate boundary locally;
    # SubLLM selects only the provider/model for those typed requests.  Missing
    # routes used to make a panel labelled "Edycja przez LLM" silently fall
    # back to a three-pattern local parser.
    RoutePolicy("twinstudio", "eda-nl2dsl", _DEFAULT),
    RoutePolicy("twinstudio", "eda-firmware-audit", _DEFAULT),
    RoutePolicy("twinstudio", "eda-conflict-chat", _DEFAULT),
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
    RoutePolicy("supervisor", "assessment", _SUPERVISOR_ASSESSMENT),
    RoutePolicy("supervisor", "delegation", _DEFAULT),
    RoutePolicy("supervisor", "review", _DEFAULT),
    RoutePolicy("subactor-proxy", "chat", _DEFAULT),
    RoutePolicy("subactor-proxy", "completion", _DEFAULT),
    RoutePolicy("premesh", "chat", _DEFAULT),
    RoutePolicy("autogrammar-gillm", "invoke", _DEFAULT),
)

ROUTES = MappingProxyType({(route.application, route.function): route for route in _ROUTE_VALUES})
