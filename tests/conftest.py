from __future__ import annotations

import pytest

from subllm import reset_provider_health


@pytest.fixture(autouse=True)
def _isolate_provider_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Keep resolve() hermetic when the operator shell exports live keys."""
    monkeypatch.setenv("SUBLLM_HEALTH_STATE_FILE", str(tmp_path / "provider-health.json"))
    monkeypatch.delenv("SUBLLM_PROVIDER_ORDER", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    reset_provider_health()
    yield
    reset_provider_health()
