from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_provider_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep resolve() hermetic when the operator shell exports live keys."""
    monkeypatch.delenv("SUBLLM_PROVIDER_ORDER", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
