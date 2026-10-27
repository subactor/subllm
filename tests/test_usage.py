from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from subllm import client_routes, complete, proxy
from subllm.client_types import CompletionResponse, _RetryableAttemptError
from subllm.errors import CompletionError
from subllm.poa import PolicyBus, make_server
from subllm.poa.errors import PoaContractError
from subllm.poa.registry import USAGE_URI
from subllm.resolver import configured_route
from subllm.usage import journal_path, query_interaction_detail, query_usage, record_attempt


def record(**kwargs):
    values = dict(request_id="same-request", application="todo2code", function="semantic", provider="zai",
                  model="glm-5.3", status="success", diagnostic_code=None, duration_ms=14,
                  usage={"prompt_tokens": 12, "completion_tokens": 4})
    record_attempt(**(values | kwargs))


def test_empty_query_is_pure_and_bus_registers_usage():
    bus = PolicyBus()
    before = bus.store.sequence
    result = bus.query({"schema": "subllm.query/v1", "process_uri": USAGE_URI})
    assert result["storage"] == "empty"
    assert result["summary"]["input_tokens"] is None
    assert not journal_path().exists()
    assert bus.store.sequence == before
    assert bus.inspect("poa://subactor.subllm/process/usage/v1")["ready"]


def test_persistence_redaction_and_null_usage():
    record(usage={"prompt_tokens": 12, "completion_tokens": 0, "secret": "NEVER-SAVE"},
           request_id="credential-in-request-id")
    record(request_id="other", usage={"input_tokens": True, "output_tokens": -1}, status="error")
    result = query_usage({})
    assert result["summary"]["attempts"] == 2
    assert result["summary"]["usage_known"] == 1
    assert result["summary"]["input_tokens"] == 12
    assert result["attempts"][0]["input_tokens"] is None
    assert result["attempts"][1]["output_tokens"] == 0
    assert journal_path().stat().st_mode & 0o777 == 0o600
    data = journal_path().read_bytes()
    assert b"NEVER-SAVE" not in data and b"credential-in-request-id" not in data
    # New interpreter, same DB: history is not a process-local cache.
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    run = subprocess.run([sys.executable, "-c", "from subllm.usage import query_usage; "
                          "print(query_usage({})['summary']['attempts'])"],
                         env=env, capture_output=True, text=True, check=True)
    assert run.stdout.strip() == "2"


def test_concurrent_first_writes_are_not_lost():
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: record(request_id=str(i)), range(40)))
    assert query_usage({})["summary"]["attempts"] == 40


def test_filters_pagination_and_summary_share_selection():
    record(status="error", usage={})
    record(provider="openrouter")
    record(application="other", request_id="second")
    result = query_usage({"application": "todo2code", "limit": "1"})
    assert result["summary"]["attempts"] == 2
    assert result["summary"]["requests"] == 1
    assert result["summary"]["errors"] == 1
    assert result["attempts"][0]["provider"] == "openrouter"
    next_page = query_usage({"application": "todo2code", "limit": 1, "before": result["next_before"]})
    assert next_page["attempts"][0]["status"] == "error"
    assert next_page["next_before"] is None
    assert query_usage({"provider": "zai", "status": "success"})["summary"]["attempts"] == 1
    assert query_usage({"since": "2099-01-01T00:00:00Z"})["summary"]["attempts"] == 0
    timestamp = result["attempts"][0]["timestamp"]
    assert query_usage({"since": timestamp, "until": timestamp})["summary"]["attempts"] >= 1


@pytest.mark.parametrize("filters", [
    {"unknown": "x"}, {"provider": "' OR 1=1--"}, {"status": "missing"}, {"limit": "0"},
    {"limit": "501"}, {"limit": True}, {"before": "-1"}, {"since": "2026-09-19"},
    {"since": "2099-01-01T00:00:00Z", "until": "2000-01-01T00:00:00Z"},
])
def test_invalid_filters_fail_closed(filters):
    with pytest.raises(PoaContractError):
        query_usage(filters)
    assert not journal_path().exists()


def test_corrupt_storage_is_not_presented_as_empty():
    journal_path().write_text("corrupt")
    with pytest.raises(PoaContractError, match="temporarily unavailable"):
        query_usage({})


def test_complete_logs_fallback_and_success_without_payload(monkeypatch):
    def invoke(route, messages, **kwargs):
        if route.provider == "zai":
            raise _RetryableAttemptError("NEVER-SAVE-ERROR", outcome="http_429")
        return CompletionResponse("NEVER-SAVE-RESPONSE", route.provider, route.wire_model,
                                  {"input_tokens": 2, "output_tokens": 1})
    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    result = complete("todo2code", "semantic", [{"role": "user", "content": "NEVER-SAVE-PROMPT"}],
                      environ={"ZAI_API_KEY": "id.secret", "OPENROUTER_API_KEY": "sk-or-v1-testkey"})
    assert result.provider == "openrouter"
    rows = query_usage({})["attempts"]
    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"error", "success"}
    assert len({row["request_id"] for row in rows}) == 1
    assert all(row["application"] == "todo2code" for row in rows)
    assert b"NEVER-SAVE" not in journal_path().read_bytes()


def test_exhausted_chain_and_unexpected_error_are_logged(monkeypatch):
    def fail(*args, **kwargs):
        raise _RetryableAttemptError("NEVER-SAVE", outcome="http_429")
    monkeypatch.setattr(client_routes, "_invoke_route", fail)
    with pytest.raises(CompletionError):
        complete("todo2code", "semantic", [{"role": "user", "content": "secret"}],
                 environ={"ZAI_API_KEY": "id.secret"})
    assert query_usage({})["summary"]["errors"] == 1
    def unexpected(*args, **kwargs):
        raise ValueError("NEVER-SAVE-UNEXPECTED")
    monkeypatch.setattr(client_routes, "_invoke_route", unexpected)
    with pytest.raises(ValueError):
        client_routes._complete_route(configured_route("todo2code", "semantic", provider="zai"), [],
                                      timeout_seconds=1, request_id="r", response_format=None, cwd=Path.cwd())
    assert query_usage({})["summary"]["errors"] == 2
    assert b"NEVER-SAVE" not in journal_path().read_bytes()


def test_failed_journal_does_not_change_completion_or_retry(monkeypatch, tmp_path, caplog):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("x")
    monkeypatch.setenv("SUBLLM_USAGE_DB", str(blocked / "usage.sqlite3"))
    calls = []
    def invoke(route, *args, **kwargs):
        calls.append(route)
        return CompletionResponse("ok", route.provider, route.wire_model)
    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    result = complete("todo2code", "semantic", [{"role": "user", "content": "q"}],
                      environ={"ZAI_API_KEY": "id.secret"})
    assert result.content == "ok" and len(calls) == 1
    assert "usage journal unavailable" in caplog.text
    assert str(blocked) not in caplog.text


def test_model_proxy_uses_same_instrumented_boundary(monkeypatch):
    monkeypatch.setattr(client_routes, "_invoke_route", lambda route, *a, **k:
                        CompletionResponse("ok", route.provider, route.wire_model, {"input_tokens": 3}))
    proxy._complete_model_direct("glm-5.3", [], application="koru-agent", function="chat",
                                 environ={"ZAI_API_KEY": "id.secret"})
    rows = query_usage({})["attempts"]
    assert len(rows) == 1 and rows[0]["application"] == "koru-agent"


@pytest.fixture
def server():
    instance = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{instance.server_port}"
    instance.shutdown()
    instance.server_close()
    thread.join(timeout=5)


def test_http_panel_and_api_are_read_only(server):
    record()
    before = journal_path().read_bytes()
    for path, marker in [("/", b"Kto korzysta z API?"), ("/", b"Zadanie (Planfile)"),
                         ("/assets/usage.js", b"extractPlanfileInfo"),
                         ("/assets/usage.css", b"ticket-badge")]:
        with urlopen(server + path, timeout=5) as response:
            assert marker in response.read()
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    with urlopen(server + "/v1/usage?provider=zai", timeout=5) as response:
        assert json.load(response)["summary"]["attempts"] == 1
        assert not response.headers.get("Access-Control-Allow-Origin")
    assert journal_path().read_bytes() == before


@pytest.mark.parametrize("headers,code", [({"Host": "evil.example"}, 421),
    ({"Origin": "https://evil.example"}, 403), ({"Sec-Fetch-Site": "cross-site"}, 403)])
def test_http_rejects_foreign_origin_and_dns_rebinding(server, headers, code):
    with pytest.raises(HTTPError) as caught:
        urlopen(Request(server + "/v1/usage", headers=headers), timeout=5)
    assert caught.value.code == code


def test_http_invalid_filter_and_storage_error(server):
    for query in ["limit=0", "provider=zai&provider=openrouter", urlencode({"schema": "evil"})]:
        with pytest.raises(HTTPError) as caught:
            urlopen(server + "/v1/usage?" + query, timeout=5)
        assert caught.value.code == 400
    journal_path().write_text("bad")
    with pytest.raises(HTTPError) as caught:
        urlopen(server + "/v1/usage", timeout=5)
    assert caught.value.code == 503


def test_query_does_not_mutate_sqlite_metadata():
    record()
    with closing(sqlite3.connect(journal_path())) as db:
        before = db.execute("PRAGMA schema_version").fetchone()
    query_usage({})
    with closing(sqlite3.connect(journal_path())) as db:
        assert db.execute("PRAGMA schema_version").fetchone() == before


def test_journal_detail_reports_unlinked_payloads_without_guessing_archive(monkeypatch):
    def unexpected_archive():
        pytest.fail('A numeric journal ID is not an archive ID')
    monkeypatch.setattr('subllm.interaction_store.get_default_interaction_store', unexpected_archive)
    record()
    row = query_usage({})['attempts'][0]
    before = journal_path().read_bytes()
    for identifier in (str(row['id']), row['request_id']):
        detail = query_interaction_detail(identifier)
        assert detail['request'] is None and detail['response'] is None
        assert detail['payload_capture'] == {
            'state': 'unlinked', 'source': 'usage-journal', 'reason': 'no_archive_reference',
        }
        assert detail['metadata']['input_tokens'] == 12
    assert journal_path().read_bytes() == before


def test_exact_archive_id_returns_stored_content_without_mutating_record(monkeypatch, server):
    record_id = 'a' * 32
    original = {'id': record_id, 'request': {'messages': [{'role': 'user', 'content': 'fixture'}]},
                'response': {'content': 'answer'}}
    def get(identifier):
        assert identifier == record_id
        return original
    monkeypatch.setattr('subllm.interaction_store.get_default_interaction_store',
                        lambda: SimpleNamespace(get_interaction=get))
    with urlopen(server + '/v1/usage/detail?id=' + record_id, timeout=5) as response:
        detail = json.load(response)
    assert detail['request'] == original['request'] and detail['response'] == original['response']
    assert detail['payload_capture'] == {'state': 'stored', 'source': 'private-archive'}
    assert 'payload_capture' not in original


@pytest.mark.parametrize('failure', ['archive', 'journal'])
def test_detail_storage_failure_is_http_503_and_keeps_driver_text_private(monkeypatch, server, failure):
    record_id = 'a' * 32 if failure == 'archive' else '1'
    if failure == 'archive':
        def unavailable(identifier):
            raise RuntimeError('PRIVATE_DRIVER_DETAIL')
        monkeypatch.setattr('subllm.interaction_store.get_default_interaction_store',
                            lambda: SimpleNamespace(get_interaction=unavailable))
    else:
        journal_path().write_text('PRIVATE_DRIVER_DETAIL')
    with pytest.raises(HTTPError) as caught:
        urlopen(server + '/v1/usage/detail?id=' + record_id, timeout=5)
    assert caught.value.code == 503
    body = caught.value.read()
    assert json.loads(body)['error']['code'] == 'USAGE-STORAGE-001'
    assert b'PRIVATE_DRIVER_DETAIL' not in body


def test_missing_or_oversized_numeric_detail_is_not_a_storage_failure(server):
    record()
    for identifier in ('9' * 32, 'missing'):
        with pytest.raises(HTTPError) as caught:
            urlopen(server + '/v1/usage/detail?id=' + identifier, timeout=5)
        assert caught.value.code == 404


def test_query_usage_search_filter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("SUBLLM_USAGE_DB", str(tmp_path / "usage.sqlite3"))
    monkeypatch.delenv("SUBLLM_POSTGRES_DSN", raising=False)
    monkeypatch.delenv("SUBLLM_DATABASE_URL", raising=False)
    monkeypatch.delenv("SUBLLM_GATEWAY_DATABASE_URL", raising=False)

    record(application="app-alpha", function="chat", provider="openai", model="gpt-4o")
    record(application="app-beta", function="edit", provider="anthropic", model="claude-3-5-sonnet")

    res_all = query_usage({})
    assert len(res_all["attempts"]) == 2

    res_search = query_usage({"search": "alpha"})
    assert len(res_search["attempts"]) == 1
    assert res_search["attempts"][0]["application"] == "app-alpha"

    res_model = query_usage({"search": "claude"})
    assert len(res_model["attempts"]) == 1
    assert res_model["attempts"][0]["model"] == "claude-3-5-sonnet"

    res_none = query_usage({"search": "nonexistent"})
    assert len(res_none["attempts"]) == 0

    with pytest.raises(PoaContractError) as caught:
        query_usage({"search": "a" * 300})
    assert caught.value.code == "USAGE-FILTER-001"


def test_explicit_archive_selection_never_returns_journal_or_payload_pages(monkeypatch, server):
    record()
    calls = []
    empty = {"schema": "subllm.usage/v1", "storage": "postgres", "attempts": [],
             "summary": {"attempts": 0}, "next_before": None}
    class Store:
        def __init__(self, **kwargs):
            pass
        def query_attempts(self, **kwargs):
            calls.append(kwargs)
            return empty
    monkeypatch.setattr("subllm.interaction_store.default_postgres_dsn", lambda: "postgresql://fixture")
    monkeypatch.setattr("subllm.interaction_store.InteractionStore", Store)
    with urlopen(server + "/v1/usage?source=archive", timeout=5) as response:
        archived = json.load(response)
    assert archived["source"] == "archive" and archived["attempts"] == []
    assert calls[0]["include_payloads"] is False
    assert query_usage({"source": "journal"})["summary"]["attempts"] == 1
    assert len(calls) == 1


@pytest.mark.parametrize("mode", ["disabled", "failed"])
def test_unavailable_selected_archive_is_http_503_not_another_history(monkeypatch, server, mode):
    record()
    def failed(**kwargs):
        raise RuntimeError("PRIVATE_ARCHIVE_DRIVER")
    monkeypatch.setattr("subllm.interaction_store.default_postgres_dsn",
                        lambda: None if mode == "disabled" else "postgresql://fixture")
    monkeypatch.setattr("subllm.interaction_store.InteractionStore", failed)
    with pytest.raises(HTTPError) as caught:
        urlopen(server + "/v1/usage?source=archive", timeout=5)
    assert caught.value.code == 503 and b"PRIVATE_ARCHIVE_DRIVER" not in caught.value.read()
    assert query_usage({"source": "journal"})["summary"]["attempts"] == 1


def test_archive_cursor_and_day_are_strict_and_day_lookup_is_exact(monkeypatch, server, captured_attempt):
    from subllm.interaction_store import archive_cursor
    store, captured, ref = captured_attempt
    cursor = "2026-10-27T23:00:00.000+02:00~" + ref["id"]
    assert archive_cursor(cursor) == ("2026-10-27T21:00:00.000Z", ref["id"])
    original = store.get_interaction
    calls = []
    def get(identifier, day=None):
        calls.append((identifier, day))
        return original(identifier, day)
    monkeypatch.setattr(store, "get_interaction", get)
    with urlopen(server + "/v1/usage/detail?" + urlencode({"id": ref["id"], "day": ref["day"]}), timeout=5) as r:
        assert json.load(r)["request"] == captured["request"]
    assert calls == [(ref["id"], ref["day"])]
    for identifier, day in ((ref["id"], "2026-02-30"), ("1", ref["day"]), (ref["id"], "../private")):
        with pytest.raises(HTTPError) as caught:
            urlopen(server + "/v1/usage/detail?" + urlencode({"id": identifier, "day": day}), timeout=5)
        assert caught.value.code == 400
    for invalid in ("2026-10-27", "2026-10-27T21:00:00Z~missing", "2026-02-30T00:00:00Z", "x" * 101):
        with pytest.raises(ValueError):
            archive_cursor(invalid)


@pytest.mark.parametrize("source", ["unknown", True, None])
def test_unknown_history_source_fails_closed(source):
    with pytest.raises(PoaContractError):
        query_usage({"source": source})


@pytest.fixture
def captured_attempt(monkeypatch, tmp_path):
    from subllm.interaction_store import InteractionStore

    store = InteractionStore(directory=tmp_path / "private-capture")
    captured = store.begin(kind="llm_attempt", caller="todo2code", target="zai/glm-5.3",
                           request={"messages": [{"role": "user", "content": "PRIVATE-PROMPT"}]},
                           correlation_id="same-request")
    captured = store.finish(captured, {"content": "PRIVATE-REPLY"}, duration_ms=14, metadata={
        "application": "todo2code", "function": "semantic", "provider": "zai", "model": "glm-5.3",
    })
    monkeypatch.setattr("subllm.interaction_store.get_default_interaction_store", lambda: store)
    return store, captured, {"id": captured["id"], "day": captured["day"]}


def test_http_ingest_links_exact_capture_without_copying_payloads(server, captured_attempt):
    _, captured, reference = captured_attempt
    payload = {
        "schema": "subllm.command/v1", "process_uri": "subllm://local/policy/command/record-usage",
        "subject": "service:todo2code", "idempotency_key": "usage.exact-capture",
        "attempt": {"request_id": "same-request", "application": "todo2code", "function": "semantic",
                    "provider": "zai", "model": "glm-5.3", "status": "success", "duration_ms": 14,
                    "usage": {"input_tokens": 12, "output_tokens": 4}, "archive_ref": reference},
    }
    for duplicate in (False, True):
        request = Request(server + "/v1/commands", data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            assert json.load(response)["duplicate"] is duplicate
    row = query_usage({})["attempts"][0]
    for identifier in (str(row["id"]), row["request_id"]):
        with urlopen(server + "/v1/usage/detail?id=" + identifier, timeout=5) as response:
            detail = json.load(response)
        assert detail["id"] == captured["id"] and detail["usage_attempt_id"] == row["id"]
        assert detail["request"] == captured["request"] and detail["response"] == captured["response"]
        assert detail["payload_capture"]["state"] == "stored"
    assert b"PRIVATE-PROMPT" not in journal_path().read_bytes()
    assert b"PRIVATE-REPLY" not in journal_path().read_bytes()
    assert "archive_ref" not in row  # List API remains payload-free.


@pytest.mark.parametrize("field,value", [("request_id", "other-request"), ("application", "other"),
    ("function", "other"), ("provider", "other"), ("model", "other"), ("status", "error")])
def test_mismatched_reference_never_discloses_another_attempt(captured_attempt, field, value):
    record(archive_ref=captured_attempt[2], **{field: value})
    with pytest.raises(PoaContractError, match="does not match") as caught:
        query_interaction_detail("1")
    assert caught.value.code == "USAGE-DETAIL-001"
    assert "PRIVATE" not in str(caught.value)


def test_missing_or_unavailable_referenced_capture_is_not_unlinked(monkeypatch, captured_attempt):
    record(archive_ref=captured_attempt[2])
    monkeypatch.setattr("subllm.interaction_store.get_default_interaction_store", lambda: None)
    with pytest.raises(PoaContractError, match="Referenced interaction archive is unavailable"):
        query_interaction_detail("1")
    def failed():
        raise RuntimeError("PRIVATE-DRIVER-DETAIL")
    monkeypatch.setattr("subllm.interaction_store.get_default_interaction_store", failed)
    with pytest.raises(PoaContractError, match="temporarily unavailable") as caught:
        query_interaction_detail("1")
    assert "PRIVATE-DRIVER-DETAIL" not in str(caught.value)


def test_legacy_rows_remain_unlinked_and_reads_do_not_migrate():
    record()
    with closing(sqlite3.connect(journal_path())) as db, db:
        db.execute("ALTER TABLE attempts DROP COLUMN archive_id")
        db.execute("ALTER TABLE attempts DROP COLUMN archive_day")
    before = journal_path().read_bytes()
    assert query_usage({})["summary"]["attempts"] == 1
    assert query_interaction_detail("1")["payload_capture"]["state"] == "unlinked"
    assert journal_path().read_bytes() == before
    record(request_id="new-request")
    assert query_interaction_detail("2")["payload_capture"]["state"] == "unlinked"


def test_shared_correlation_requires_an_individual_attempt(captured_attempt):
    record(archive_ref=captured_attempt[2])
    record(provider="openrouter", status="error")
    correlation = query_usage({})["attempts"][0]["request_id"]
    with pytest.raises(PoaContractError, match="individual usage attempt"):
        query_interaction_detail(correlation)
    assert query_interaction_detail("1")["id"] == captured_attempt[1]["id"]


@pytest.mark.parametrize("reference", [{"id": "a" * 32}, {"id": "a" * 32, "day": "2026-02-30"},
    {"id": "a" * 32, "day": "2026-10-27", "request": "PRIVATE"},
    {"id": "../PRIVATE", "day": "2026-10-27"}, "PRIVATE"])
def test_ingest_rejects_malformed_archive_references(reference):
    document = {
        "schema": "subllm.command/v1", "process_uri": "subllm://local/policy/command/record-usage",
        "subject": "service:todo2code", "idempotency_key": "usage.invalid-capture",
        "attempt": {"request_id": "same-request", "application": "todo2code", "function": "semantic",
                    "provider": "zai", "model": "glm-5.3", "status": "success", "duration_ms": 14,
                    "usage": {}, "archive_ref": reference},
    }
    with pytest.raises(PoaContractError) as caught:
        PolicyBus().command(document)
    assert caught.value.code == "USAGE-EVENT-001" and "PRIVATE" not in str(caught.value)
    assert not journal_path().exists()

