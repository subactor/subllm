from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from starlette.testclient import TestClient
from test_gateway import TOKEN, auth

from subllm.gateway import create_app
from subllm.interaction_store import InteractionStore
from subllm.usage import record_attempt


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_GATEWAY_TOKEN", TOKEN)
    config = {
        "allowed_hosts": ["testserver"],
        "archive_directory": str(tmp_path / "archive"),
        "clients": {"first": {"token_env": "TEST_GATEWAY_TOKEN", "llm": True, "mcp": []}},
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
