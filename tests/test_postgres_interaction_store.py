from __future__ import annotations

import builtins
import os
from pathlib import Path

import pytest
from conftest import _isolate_postgres, _isolated_postgres_dsn

from subllm.client_types import CompletionResponse
from subllm.interaction_context import begin_attempt, finish_attempt
from subllm.interaction_store import (
    InteractionStore,
    default_postgres_dsn,
    set_default_interaction_store,
)
from subllm.resolver import configured_route
from subllm.types import ResolvedRoute
from subllm.usage import query_interaction_detail, query_usage


def test_postgres_fixture_does_not_inherit_application_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUBLLM_TEST_POSTGRES_DSN", raising=False)
    for name in ("SUBLLM_POSTGRES_DSN", "SUBLLM_DATABASE_URL", "SUBLLM_GATEWAY_DATABASE_URL"):
        monkeypatch.setenv(name, "postgresql://operator@127.0.0.1:5432/shared")
    monkeypatch.setenv("SUBLLM_USE_LOCAL_POSTGRES", "1")
    _isolate_postgres(monkeypatch)
    assert default_postgres_dsn() is None


@pytest.mark.parametrize("host", ["127.0.0.1", "[::1]"])
def test_postgres_fixture_accepts_explicit_loopback_test_database(host: str) -> None:
    dsn = f"postgresql://postgres@{host}:5432/usage_test_fixture"
    assert _isolated_postgres_dsn({"SUBLLM_TEST_POSTGRES_DSN": dsn}) == dsn


def test_postgres_fixture_cannot_inherit_libpq_routing_or_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    dsn = "postgresql://postgres@127.0.0.1:5432/usage_test_fixture"
    monkeypatch.setenv("SUBLLM_TEST_POSTGRES_DSN", dsn)
    inherited = {"PGHOSTADDR": "192.0.2.1", "PGSERVICE": "operator", "PGPASSFILE": "/operator/passwords"}
    for name, value in inherited.items():
        monkeypatch.setenv(name, value)
    _isolate_postgres(monkeypatch)
    assert not set(inherited).intersection(os.environ)
    assert default_postgres_dsn() == dsn


def test_postgres_fixture_validation_does_not_require_optional_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    original_import = builtins.__import__

    def without_postgres_driver(name, *args, **kwargs):
        if name == "psycopg" or name.startswith("psycopg."):
            raise ModuleNotFoundError("Optional PostgreSQL driver is unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_postgres_driver)
    dsn = "postgresql://postgres@127.0.0.1:5432/usage_test_fixture"
    assert _isolated_postgres_dsn({"SUBLLM_TEST_POSTGRES_DSN": dsn}) == dsn


@pytest.mark.parametrize("dsn", [
    "postgresql://postgres@127.0.0.1:5432/shared",
    "postgresql://postgres@192.0.2.1:5432/usage_test_fixture",
    "postgresql://postgres@localhost:5432/usage_test_fixture",
    "postgresql://postgres@127.0.0.1:5432/usage_test_",
    "host=127.0.0.1 hostaddr=192.0.2.1 dbname=usage_test_fixture",
    "host=127.0.0.1 dbname=usage_test_fixture service=operator",
    "postgresql://postgres@127.0.0.1:5432/usage_test_fixture?host=192.0.2.1",
    "postgresql://postgres@127.0.0.1:5432/usage_test_fixture?hostaddr=192.0.2.1",
    "postgresql://postgres@127.0.0.1:5432/usage_test_fixture#operator",
    "postgresql://postgres@127.0.0.1:99999/usage_test_fixture",
    "postgresql://postgres@127.0.0.1:0/usage_test_fixture",
    "postgresql://postgres@127.0.0.1:5432/usage_test_%2Fshared",
    "postgresql://post\ngres@127.0.0.1:5432/usage_test_fixture",
    "postgresql://operator@other@127.0.0.1:5432/usage_test_fixture",
    r"postgresql://operator\@127.0.0.1:5432/usage_test_fixture",
    "postgresql://post%gres@127.0.0.1:5432/usage_test_fixture",
    "not a database connection string",
])
def test_postgres_fixture_rejects_unsafe_opt_in(dsn: str) -> None:
    with pytest.raises(pytest.UsageError, match="isolated loopback usage_test_") as failure:
        _isolated_postgres_dsn({"SUBLLM_TEST_POSTGRES_DSN": dsn})
    assert dsn not in str(failure.value)


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

        # Search filter verification in Postgres
        res_search_prompt = query_usage({"search": "prompt test"}, database=dsn)
        assert any(a["id"] == record["id"] for a in res_search_prompt["attempts"])

        res_search_resp = query_usage({"search": "response test"}, database=dsn)
        assert any(a["id"] == record["id"] for a in res_search_resp["attempts"])

        res_search_none = query_usage({"search": "unmatched_search_token_xyz_99"}, database=dsn)
        assert not any(a["id"] == record["id"] for a in res_search_none["attempts"])
    finally:
        set_default_interaction_store(None)
