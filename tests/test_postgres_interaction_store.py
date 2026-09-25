from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from subllm.client_types import CompletionResponse
from subllm.interaction_context import begin_attempt, finish_attempt
from subllm.interaction_store import (
    InteractionStore,
    default_postgres_dsn,
    get_default_interaction_store,
    set_default_interaction_store,
)
from subllm.resolver import configured_route
from subllm.types import ResolvedRoute
from subllm.usage import query_interaction_detail, query_usage


def test_default_postgres_dsn_environment_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUBLLM_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("SUBLLM_DATABASE_URL", raising=False)
    monkeypatch.delenv("SUBLLM_GATEWAY_DATABASE_URL", raising=False)
    monkeypatch.setenv("SUBLLM_USE_LOCAL_POSTGRES", "0")

    assert default_postgres_dsn() is None

    monkeypatch.setenv("SUBLLM_GATEWAY_DATABASE_URL", "postgresql://gateway:pass@127.0.0.1:5432/gw")
    assert default_postgres_dsn() == "postgresql://gateway:pass@127.0.0.1:5432/gw"

    monkeypatch.setenv("SUBLLM_DATABASE_URL", "postgresql://db:pass@127.0.0.1:5432/db")
    assert default_postgres_dsn() == "postgresql://db:pass@127.0.0.1:5432/db"

    monkeypatch.setenv("SUBLLM_POSTGRES_DSN", "postgresql://user:pass@127.0.0.1:5432/main")
    assert default_postgres_dsn() == "postgresql://user:pass@127.0.0.1:5432/main"


def test_interaction_store_query_with_payloads(tmp_path: Path) -> None:
    store = InteractionStore(tmp_path / "archive")
    record = store.begin(
        kind="llm_attempt",
        caller="test-app",
        target="openai/gpt-5",
        request={"messages": [{"role": "user", "content": "Hello SubLLM"}]},
    )
    store.finish(
        record,
        {"content": "Hello World", "usage": {"prompt_tokens": 5, "completion_tokens": 3}},
        duration_ms=50,
        metadata={"provider": "openai", "model": "gpt-5"},
    )

    day = record["day"]
    # Default query strips request and response
    summary_rows = store.query(day, include_payloads=False)
    assert len(summary_rows) == 1
    assert "request" not in summary_rows[0]
    assert "response" not in summary_rows[0]

    # Query with include_payloads=True retains prompt and response
    full_rows = store.query(day, include_payloads=True)
    assert len(full_rows) == 1
    assert full_rows[0]["request"]["messages"] == [{"role": "user", "content": "Hello SubLLM"}]
    assert full_rows[0]["response"]["content"] == "Hello World"

    # get_interaction fetches full document by ID
    single = store.get_interaction(record["id"], day=day)
    assert single is not None
    assert single["id"] == record["id"]
    assert single["request"]["messages"] == [{"role": "user", "content": "Hello SubLLM"}]
    assert single["response"]["content"] == "Hello World"


def test_interaction_context_captures_full_prompts_and_responses(tmp_path: Path) -> None:
    store = InteractionStore(tmp_path / "archive")
    set_default_interaction_store(store)
    try:
        cr = configured_route("subactor-proxy", "chat")
        route = ResolvedRoute(
            application="test-app",
            application_name=cr.application_name,
            application_url=cr.application_url,
            function=cr.function,
            provider="test-provider",
            model="test-wire",
            priority=cr.priority,
            api_base=cr.api_base,
            api_key_env=cr.api_key_env,
            litellm_model=cr.litellm_model,
            wire_model="test-wire",
            extra_headers=cr.extra_headers,
            transport=cr.transport,
            api_key="test-key",
        )
        messages = [{"role": "user", "content": "Czy baza zapisuje prompty?"}]
        archive = begin_attempt(route, messages, None, request_id="custom-req-id-1")
        assert archive is not None

        response = CompletionResponse(
            content="Tak, zapisuje!",
            provider="test-provider",
            model="test-wire",
            usage={"prompt_tokens": 10, "completion_tokens": 6},
            finish_reason="stop",
        )
        finish_attempt(archive, route, response, None, duration_ms=25)

        saved = store.get_interaction(archive[1]["id"])
        assert saved is not None
        assert saved["caller"] == "test-app"
        assert saved["request"]["messages"] == messages
        assert saved["response"]["content"] == "Tak, zapisuje!"
        assert saved["metadata"]["input_tokens"] == 10
        assert saved["metadata"]["output_tokens"] == 6
    finally:
        set_default_interaction_store(None)


def test_query_usage_postgres_integration(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    dsn = default_postgres_dsn()
    if not dsn:
        pytest.skip("PostgreSQL not reachable on local development port")

    store = InteractionStore(tmp_path / "archive", postgres_dsn=dsn)
    set_default_interaction_store(store)
    try:
        record = store.begin(
            kind="llm_attempt",
            caller="pg-test-client",
            target="test-prov/pg-model",
            request={"messages": [{"role": "user", "content": "PG prompt test"}]},
            correlation_id="pg-corr-1",
        )
        store.finish(
            record,
            {"content": "PG response test", "usage": {"prompt_tokens": 8, "completion_tokens": 12}},
            duration_ms=45,
            metadata={"provider": "test-prov", "model": "pg-model", "input_tokens": 8, "output_tokens": 12},
        )

        res = query_usage({"application": "pg-test-client"}, database=dsn)
        assert res["storage"] == "postgres"
        assert len(res["attempts"]) >= 1
        found = next((a for a in res["attempts"] if a["id"] == record["id"]), None)
        assert found is not None
        assert found["request"]["messages"] == [{"role": "user", "content": "PG prompt test"}]
        assert found["response"]["content"] == "PG response test"
        assert found["input_tokens"] == 8
        assert found["output_tokens"] == 12

        detail = query_interaction_detail(record["id"])
        assert detail is not None
        assert detail["id"] == record["id"]
        assert detail["response"]["content"] == "PG response test"
    finally:
        set_default_interaction_store(None)
