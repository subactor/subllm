from __future__ import annotations

import json
from pathlib import Path

from subllm import MODELS, PROVIDERS

ROOT = Path(__file__).resolve().parents[1]
ADOPTED = ROOT / "policy" / "adopted"


def test_adopted_catalog_matches_python_providers() -> None:
    catalog = json.loads((ADOPTED / "strategy-catalog.json").read_text(encoding="utf-8"))
    by_id = {row["id"]: row for row in catalog["strategies"]}
    assert set(by_id) == set(PROVIDERS)
    for provider_id, provider in PROVIDERS.items():
        row = by_id[provider_id]
        assert row["credentialEnv"] == provider.api_key_env
        assert row["provider"] == provider.id
        assert row["transport"] == provider.transport
        assert row["apiBase"] == provider.api_base
        assert "gpt-5.6-sol" not in row.get("allowedModels", []) or provider_id == "cursor"
        if provider_id == "openrouter":
            assert "gpt-5.6-sol" in row.get("forbiddenModels", [])


def test_adopted_env_declares_sol_not_on_openrouter() -> None:
    text = (ADOPTED / "credential-strategies.env").read_text(encoding="utf-8")
    assert "CURSOR_DEFAULT_MODEL=gpt-5.6-sol" in text
    assert "OPENROUTER_DEFAULT_MODEL=glm-5.2" in text
    assert "CURSOR_FALLBACK_ORDER=gpt-5.6-sol,grok-4.6" in text
    assert "CURSOR_ONLY_MODELS=gpt-5.6-sol,grok-4.6" in text
    assert "openai/gpt-5.6-sol" not in text


def test_python_catalog_keeps_sol_off_openrouter() -> None:
    assert "openrouter" not in MODELS["gpt-5.6-sol"].providers
    assert "cursor" in MODELS["gpt-5.6-sol"].providers
    assert "openrouter" not in MODELS["grok-4.6"].providers
    assert "cursor" in MODELS["grok-4.6"].providers
    assert MODELS["grok-4.6"].providers["cursor"].wire_model == "grok-4.6"
