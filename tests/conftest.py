from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_provider_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUBLLM_PROVIDER_ORDER", raising=False)
