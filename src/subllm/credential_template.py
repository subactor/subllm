"""Annotated credential file template and provider-order presets (`subllm env template`)."""
from __future__ import annotations

from .policy import PROVIDERS, SUBLLM_PROVIDER_ORDER

# id -> (order, what it optimises). Only providers that are candidates of a route and have a valid
# credential (or an enabled local CLI) take part; the rest of a list is simply skipped.
PRESETS: dict[str, tuple[str, str]] = {
    "balanced": ("agy,zai,openrouter", "Gemini Flash first, then GLM-5.3, then OpenRouter (default)"),
    "high-performance": (
        "claude-cli,agy-cli,codex-cli,claude,codex,agy,zai,openrouter",
        "strongest models first: Claude Sonnet 5 / Opus, then Codex, then Gemini; needs the local CLIs "
        "logged in and [providers.*-cli] enabled = true in subllm.toml",
    ),
    "api-only": ("claude,codex,agy,zai,openrouter", "paid APIs by quality, no local CLI, no subscription"),
    "cheap": ("ollama,agy,openrouter", "local Ollama first, then Gemini Flash, then OpenRouter Flash"),
    "free": ("agy,openrouter", "free tiers only (Gemini free tier has no Pro quota; OpenRouter free requests)"),
}

# provider -> (label, where to get the credential, model used by the shared routes)
_DOCS: dict[str, tuple[str, str, str]] = {
    "zai": ("Z.AI Coding Plan", "{API Key ID}.{signature secret} from https://z.ai", "glm-5.3"),
    "agy": ("Google AI Studio (Gemini API)", "https://aistudio.google.com/api-keys",
            "gemini-3.8-flash (Pro models need billing on the Google project)"),
    "codex": ("OpenAI API", "https://platform.openai.com/api-keys", "gpt-5.6-sol"),
    "claude": ("Anthropic API", "https://console.anthropic.com/settings/keys", "claude-sonnet-5"),
    "cursor": ("Cursor SDK", "https://cursor.com/dashboard", "gpt-5.6-sol, grok-4.6"),
    "ollama": ("Ollama (local or remote OpenAI-compatible server)", "any non-empty token; server at 127.0.0.1:11434",
               "qwen3-coder:30b"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/keys", "glm-5.3-flash and route extras"),
}
_LOCAL_LOGINS = (
    ("claude-cli", "Claude Code login (subscription)", "claude-sonnet-5"),
    ("agy-cli", "Google Antigravity login (subscription)", "claude-sonnet-4-6, gemini via Antigravity"),
    ("codex-cli", "Codex / ChatGPT login (subscription)", "gpt-5.6-sol, gpt-5.6-luna"),
)


def render() -> str:
    lines = [
        "# One local credential file for SubLLM consumers in this workspace.",
        "# Keep the real .env at mode 0600 and never commit it.",
        "# Manage it without editing by hand:  subllm env list | set <provider> | unset | verify | order",
        "# Empty values are ignored; a provider without a valid key is skipped, never an error.",
        "",
    ]
    for provider, (label, where, model) in _DOCS.items():
        variable = PROVIDERS[provider].api_key_env
        lines += [f"# {label} -> provider \"{provider}\" -> {model}", f"#   credential: {where}", f"{variable}=", ""]
    lines += ["# Local logins (no key here). Off by default; enable in subllm.toml and add the id to the order:"]
    for provider, label, model in _LOCAL_LOGINS:
        lines.append(f"#   {provider}: {label} -> {model}")
    lines += [
        "",
        "# Provider queue (first = tried first, the rest are failover). Pick ONE line.",
        "# Ids: " + ", ".join(PROVIDERS) + ". Unknown ids fail closed.",
        "# Leave it empty to use the priorities in subllm.toml.",
    ]
    for name, (order, note) in PRESETS.items():
        prefix = "" if name == "balanced" else "# "
        lines += [f"# {name}: {note}", f"{prefix}{SUBLLM_PROVIDER_ORDER}={order}"]
    return "\n".join(lines) + "\n"
