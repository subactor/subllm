from __future__ import annotations

import os
import re
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest

from subllm import reset_provider_health


def _isolated_postgres_dsn(environ: Mapping[str, str]) -> str | None:
    """Accept a plain PostgreSQL URI without importing the optional driver."""
    dsn = environ.get("SUBLLM_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        return None
    message = "SUBLLM_TEST_POSTGRES_DSN must be a plain PostgreSQL URI for an isolated loopback usage_test_ database"
    if (
        not dsn.startswith(("postgresql://", "postgres://"))
        or any(character.isspace() or ord(character) < 32 for character in dsn)
        or "\\" in dsn
        or re.search(r"%(?![0-9A-Fa-f]{2})", dsn)
    ):
        raise pytest.UsageError(message)
    try:
        uri = urlsplit(dsn)
        hostname = uri.hostname
        port = uri.port
    except ValueError:
        raise pytest.UsageError(message) from None
    if (
        uri.scheme not in {"postgresql", "postgres"}
        or hostname not in {"127.0.0.1", "::1"}
        or port == 0
        or uri.netloc.count("@") > 1
        or re.fullmatch(r"/usage_test_[A-Za-z0-9_]+", unquote(uri.path)) is None
        or "?" in dsn
        or "#" in dsn
    ):
        raise pytest.UsageError(message)
    return dsn


def _isolate_postgres(monkeypatch: pytest.MonkeyPatch) -> None:
    dsn = _isolated_postgres_dsn(os.environ)
    for name in tuple(os.environ):
        if name.startswith("PG"):
            monkeypatch.delenv(name)
    for name in ("SUBLLM_POSTGRES_DSN", "SUBLLM_DATABASE_URL", "SUBLLM_GATEWAY_DATABASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SUBLLM_USE_LOCAL_POSTGRES", "0")
    if dsn:
        monkeypatch.setenv("SUBLLM_POSTGRES_DSN", dsn)


@pytest.fixture(autouse=True)
def _isolate_provider_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """Keep resolve() hermetic when the operator shell exports live keys."""
    credential_file = tmp_path / "empty-credentials.env"
    credential_file.write_text("# No operator credentials in tests.\n", encoding="utf-8")
    credential_file.chmod(0o600)
    monkeypatch.setenv("SUBLLM_ENV_FILE", str(credential_file))
    _isolate_postgres(monkeypatch)
    monkeypatch.setenv("SUBLLM_HEALTH_STATE_FILE", str(tmp_path / "provider-health.json"))
    monkeypatch.delenv("SUBLLM_PROVIDER_ORDER", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("SUBLLM_USAGE_DB", str(tmp_path / "usage.sqlite3"))
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

