from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import pytest
from starlette.testclient import TestClient
from test_gateway import OTHER, TOKEN, auth

from subllm.gateway import create_app
from subllm.interaction_store import InteractionStore
from subllm.usage import record_attempt


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GATEWAY_TOKEN", TOKEN)
    monkeypatch.setenv("TEST_GATEWAY_OTHER", OTHER)
    config = {
        "allowed_hosts": ["testserver"],
        "archive_directory": str(tmp_path / "archive"),
        "clients": {
            "first": {"token_env": "TEST_GATEWAY_TOKEN", "llm": True, "mcp": []},
            "other": {"token_env": "TEST_GATEWAY_OTHER", "llm": False, "mcp": []},
        },
    }
    return config, InteractionStore(tmp_path / "archive")


def test_history_merges_metadata_only_llm_attempts(setup, monkeypatch, tmp_path):
    config, store = setup
    config["clients"]["first"]["read_all"] = True
    database = tmp_path / "usage.sqlite3"
    config["usage_database"] = str(database)
    monkeypatch.setenv("SUBLLM_USAGE_DB", str(database))

    assert record_attempt(
        request_id="legacy-request-1",
        application="validator-agent",
        function="patch-review",
        provider="zai",
        model="glm-5.3",
        status="success",
        diagnostic_code=None,
        duration_ms=12,
        usage={"input_tokens": 9, "output_tokens": 3},
    )
    day = datetime.now(UTC).date().isoformat()
    with TestClient(create_app(config, store)) as client:
        rows = client.get(f"/v1/interactions?day={day}", headers=auth()).json()["data"]
        assert len(rows) == 1
        row = rows[0]
        assert row["kind"] == "llm_attempt"
        assert row["capture"] == "metadata-only"
        assert "request" not in row and "response" not in row
        assert row["caller"] == "validator-agent"
        assert row["metadata"]["input_tokens"] == 9
        detail = client.get(f"/v1/interactions?day={day}&id={row['id']}", headers=auth()).json()["data"]
        assert detail["request"]["captured"] is False
        assert detail["response"]["captured"] is False
        assert "legacy-request-1" not in json.dumps(detail)


def test_gateway_js_assets_session_persistence_contract():
    js_text = files("subllm").joinpath("assets", "gateway.js").read_text(encoding="utf-8")
    assert 'sessionStorage.getItem("subllm.gateway.credential")' in js_text or 'sessionStorage.getItem(SESSION_KEY)' in js_text
    assert 'sessionStorage.setItem(SESSION_KEY' in js_text
    assert 'sessionStorage.removeItem(SESSION_KEY)' in js_text
    # Verify logout clears session
    assert '$("disconnect").onclick' in js_text
    assert 'forgetCredential()' in js_text


def test_history_caller_isolation_and_filters(setup, monkeypatch, tmp_path):
    config, store = setup
    database = tmp_path / "usage.sqlite3"
    config["usage_database"] = str(database)
    monkeypatch.setenv("SUBLLM_USAGE_DB", str(database))

    # Record attempts for two different callers
    assert record_attempt(
        request_id="req-first-1",
        application="first",
        function="task",
        provider="openrouter",
        model="deepseek",
        status="success",
        diagnostic_code=None,
        duration_ms=25,
        usage={"input_tokens": 10, "output_tokens": 5},
    )
    assert record_attempt(
        request_id="req-other-1",
        application="other",
        function="task",
        provider="zai",
        model="glm-5.3",
        status="error",
        diagnostic_code="SUBLLM-TEST-ERR",
        duration_ms=40,
        usage={"input_tokens": 5, "output_tokens": 0},
    )

    day = datetime.now(UTC).date().isoformat()
    with TestClient(create_app(config, store)) as client:
        # 'first' should only see their own caller's attempts
        rows_first = client.get(f"/v1/interactions?day={day}", headers=auth(TOKEN)).json()["data"]
        callers_first = [r["caller"] for r in rows_first]
        assert "first" in callers_first
        assert "other" not in callers_first

        # 'other' should only see their own caller's attempts
        rows_other = client.get(f"/v1/interactions?day={day}", headers=auth(OTHER)).json()["data"]
        callers_other = [r["caller"] for r in rows_other]
        assert "other" in callers_other
        assert "first" not in callers_other

        # Filtering by status
        filtered_rows = client.get(f"/v1/interactions?day={day}&status=error", headers=auth(OTHER)).json()["data"]
        assert len(filtered_rows) == 1
        assert filtered_rows[0]["status"] == "error"

        # Secret safety: ensure no raw credentials leak in responses
        dumped = json.dumps(rows_first)
        assert TOKEN not in dumped
        assert OTHER not in dumped
