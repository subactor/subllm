from __future__ import annotations

from pathlib import Path

import pytest

from subllm import reset_provider_health


@pytest.fixture(autouse=True)
def _isolate_provider_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Keep resolve() hermetic when the operator shell exports live keys."""
    credential_file = tmp_path / "empty-credentials.env"
    credential_file.write_text("# No operator credentials in tests.\n", encoding="utf-8")
    credential_file.chmod(0o600)
    monkeypatch.setenv("SUBLLM_ENV_FILE", str(credential_file))
    monkeypatch.setenv("SUBLLM_HEALTH_STATE_FILE", str(tmp_path / "provider-health.json"))
    monkeypatch.delenv("SUBLLM_PROVIDER_ORDER", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    reset_provider_health()
    yield
    reset_provider_health()


@pytest.fixture
def enabled_cursor_policy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Provide an isolated policy configuration with cursor enabled for cursor-specific unit tests."""
    policy_file = tmp_path / "subllm-cursor-enabled.toml"
    root_policy = Path(__file__).resolve().parent.parent / "subllm.toml"
    text = root_policy.read_text(encoding="utf-8").replace(
        "[providers.cursor]\nenabled = false",
        "[providers.cursor]\nenabled = true",
    )
    policy_file.write_text(text, encoding="utf-8")
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy_file))
    return policy_file

