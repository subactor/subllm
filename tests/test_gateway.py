from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from starlette.testclient import TestClient

from subllm.client_types import CompletionResponse
from subllm.gateway import create_app
from subllm.interaction_store import InteractionStore, utc_now

TOKEN = "test-client-credential-" + "x" * 32
OTHER = "test-other-credential-" + "y" * 32


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


def auth(token=TOKEN):
    return {"Authorization": "Bearer " + token}


def test_llm_archive_isolation_and_deep_link(setup, monkeypatch):
    config, store = setup
    monkeypatch.setattr(
        "subllm.gateway._complete_model_direct",
        lambda *a, **kw: CompletionResponse("<script>private response</script>", "zai", "glm-5.3", {}, "stop"),
    )
    with TestClient(create_app(config, store)) as client:
        assert client.get("/v1/interactions").status_code == 401
        assert client.get("/v1/interactions", headers={**auth(), "Origin": "https://evil.example"}).status_code == 403
        assert client.get("/v1/interactions", headers={**auth(), "Host": "evil.example"}).status_code == 421
        r = client.post(
            "/v1/chat/completions",
            headers=auth(),
            json={"model": "glm-5.3", "messages": [{"role": "user", "content": "private prompt"}]},
        )
        assert r.status_code == 200, r.text
        day, rid = r.headers["x-subllm-interaction"].split("/")
        detail = client.get(f"/v1/interactions?day={day}&id={rid}", headers=auth()).json()["data"]
        assert detail["request"]["messages"][0]["content"] == "private prompt"
        assert "private response" in json.dumps(detail["response"])
        assert detail["metadata"]["provider"] == "zai"
        assert TOKEN not in json.dumps(detail)
        assert client.get(f"/v1/interactions?day={day}&id={rid}", headers=auth(OTHER)).json()["data"] is None
        rows = client.get("/v1/interactions", headers=auth()).json()["data"]
        assert len(rows) == 1 and "request" not in rows[0] and "response" not in rows[0]
        assert client.get("/favicon.ico").status_code == 200
        assert "no-store" in r.headers["cache-control"]


def test_storage_failure_does_not_call_llm(setup, monkeypatch):
    config, store = setup

    def broken(**kwargs):
        raise OSError("no disk")

    def forbidden(*args, **kwargs):
        pytest.fail("A paid call must not happen if initial archive persistence fails")

    monkeypatch.setattr(store, "begin", broken)
    monkeypatch.setattr("subllm.gateway._complete_model_direct", forbidden)
    with TestClient(create_app(config, store)) as client:
        r = client.post(
            "/v1/chat/completions",
            headers=auth(),
            json={"model": "glm-5.3", "messages": [{"role": "user", "content": "test"}]},
        )
        assert r.status_code == 503


def test_response_survives_finish_failure_without_retry(setup, monkeypatch):
    config, store = setup
    calls = []

    def complete(*args, **kwargs):
        calls.append(1)
        return CompletionResponse("done", "zai", "glm-5.3", {}, "stop")

    def broken(*args, **kwargs):
        raise OSError("disk full after paid response")

    monkeypatch.setattr("subllm.gateway._complete_model_direct", complete)
    monkeypatch.setattr(store, "finish", broken)
    with TestClient(create_app(config, store)) as client:
        r = client.post(
            "/v1/chat/completions",
            headers=auth(),
            json={"model": "glm-5.3", "messages": [{"role": "user", "content": "test"}]},
        )
        assert r.status_code == 200
        assert r.headers["x-subllm-archive-status"] == "pending"
        assert len(calls) == 1


def test_daily_store_concurrent_and_midnight(tmp_path, monkeypatch):
    store = InteractionStore(tmp_path / "private")
    monkeypatch.setattr("subllm.interaction_store.utc_now", lambda: "2026-09-19T23:59:59.999Z")

    def begin(i):
        return store.begin(kind="llm", caller="first", target="glm", request={"number": i})

    with ThreadPoolExecutor(8) as pool:
        records = list(pool.map(begin, range(24)))
    monkeypatch.setattr("subllm.interaction_store.utc_now", lambda: "2026-09-20T00:00:01.001Z")
    for r in records:
        store.finish(r, {"answer": 42}, duration_ms=1002)
    assert len(store.query("2026-09-19")) == 24
    assert store.query("2026-09-20") == []
    assert not (tmp_path / "private/2026-09-20.sqlite3").exists()
    assert store.query("2026-09-19", records[0]["id"])["finished_at"].startswith("2026-09-20")
    assert (tmp_path / "private/2026-09-19.sqlite3").stat().st_mode & 0o077 == 0


def test_stdio_mcp_real_transport_and_tool_error(setup, tmp_path):
    config, store = setup
    fixture = tmp_path / "server.py"
    fixture.write_text("""import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 if m['method']=='initialize':
  result={'protocolVersion':'2025-06-18','capabilities':{'tools':{}},'serverInfo':{'name':'test','version':'1'}}
 elif m['method']=='tools/call':
  result={'isError':True,'content':[{'type':'text','text':'Expected failure: argument not found'}]}
 else: result={'tools':[]}
 print(json.dumps({'jsonrpc':'2.0','id':m['id'],'result':result}),flush=True)
""")
    config["mcp"] = {"fixture": {"command": sys.executable, "args": [str(fixture)]}}
    config["clients"]["first"]["mcp"] = ["fixture"]
    config["clients"]["other"]["mcp"] = ["fixture"]
    headers = {**auth(), "Accept": "application/json, text/event-stream"}
    with TestClient(create_app(config, store)) as client:
        r = client.post(
            "/mcp/fixture",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        assert r.status_code == 200, r.text
        assert '"name":"test"' in r.text
        session = r.headers["mcp-session-id"]
        headers.update({"MCP-Session-Id": session, "MCP-Protocol-Version": "2025-06-18"})
        r = client.post("/mcp/fixture", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert r.status_code == 202
        r = client.post(
            "/mcp/fixture",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": "tool1",
                "method": "tools/call",
                "params": {"name": "fail", "arguments": {"path": "missing"}},
            },
        )
        assert r.status_code == 200 and '"isError":true' in r.text
        rows = store.query(utc_now()[:10])
        errors = [row for row in rows if row["status"] == "error"]
        assert len(errors) == 1 and errors[0]["diagnostic"]["code"] == "SUBLLM-MCP-TOOL"
        r = client.post(
            "/mcp/fixture", headers={**headers, **auth(OTHER)}, json={"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
        )
        assert r.status_code == 404
        assert client.delete("/mcp/fixture", headers=headers).status_code == 200


def test_operational_projection_matches_pinned_logs_schema(setup):
    import hashlib
    import sqlite3
    from pathlib import Path

    import jsonschema

    from subllm.gateway_diagnostics import diagnostic
    from subllm.interaction_events import canonical

    _, store = setup
    r = store.begin(kind="mcp", caller="first", target="tool", request={"private": "do-not-publish"})
    store.finish(r, {"private": "response"}, diagnostic=diagnostic("SUBLLM-MCP-TOOL"))
    schema = json.loads((Path(__file__).parents[1] / "policy/adopted/logs/event.schema.json").read_text())
    with sqlite3.connect(store.directory / (r["day"] + ".sqlite3")) as db:
        rows = db.execute("SELECT event FROM operational_events ORDER BY sequence").fetchall()
    previous = "0" * 64
    for row in rows:
        event = json.loads(row[0])
        jsonschema.validate(event, schema, format_checker=jsonschema.FormatChecker())
        assert event["previousHash"] == previous
        previous = event.pop("eventHash")
        assert hashlib.sha256(canonical(event).encode()).hexdigest() == previous
        assert "do-not-publish" not in row[0] and "private" not in row[0]


def test_attempt_capture_keeps_failover_reason_and_response(setup):
    from types import SimpleNamespace

    from subllm.client_types import _RetryableAttemptError
    from subllm.interaction_context import ACTIVE_ARCHIVE, begin_attempt, finish_attempt

    _, store = setup
    parent = store.begin(kind="llm", caller="first", target="glm", request={})
    route = SimpleNamespace(
        wire_model="glm", provider="zai", application="subactor-proxy", function="chat", model_parameters={}
    )
    token = ACTIVE_ARCHIVE.set((store, parent))
    try:
        attempt = begin_attempt(route, [{"role": "user", "content": "prompt"}], None)
        error = _RetryableAttemptError("not public", outcome="http_429")
        error.private_exchange = {"response": {"error": {"message": "quota exceeded"}}}
        finish_attempt(attempt, route, None, error, 77)
    finally:
        ACTIVE_ARCHIVE.reset(token)
    record = store.query(parent["day"], attempt[1]["id"])
    assert record["diagnostic"]["httpStatus"] == 429
    assert record["diagnostic"]["code"] == "SUBLLM-UPSTREAM-LIMIT"
    assert record["metadata"]["parent_id"] == parent["id"]
    assert record["response"]["exchange"]["response"]["error"]["message"] == "quota exceeded"


def test_read_queries_do_not_create_storage(tmp_path):
    store = InteractionStore(tmp_path / "not-created")
    assert store.query("2026-09-18") == []
    assert not store.directory.exists()
    for day in ["../../etc/passwd", "2026-99-99", "2026-09-19' OR 1=1"]:
        with pytest.raises(ValueError):
            store.query(day)


@pytest.mark.parametrize("credential", ["credential-example", 'credential-"quoted"-example'])
def test_worker_private_exchange_preserves_body_without_credential(monkeypatch, credential):
    import io
    from urllib.error import HTTPError

    from subllm import openai_worker

    source = {
        "wire_model": "glm",
        "messages": [{"role": "user", "content": "prompt"}],
        "model_parameters": {},
        "request_fields": {},
        "response_format": None,
        "api_base": "https://example.invalid",
        "api_key": credential,
        "extra_headers": {},
        "capture_exchange": True,
    }

    def denied(request):
        raise HTTPError(
            request.full_url,
            429,
            "rate limited",
            {},
            io.BytesIO(json.dumps({"error": {"message": "quota for " + credential + " exhausted"}}).encode()),
        )

    monkeypatch.setattr(openai_worker, "urlopen", denied)
    result = openai_worker._execute(source)
    assert result["outcome"] == "http_429"
    assert result["exchange"]["request"]["messages"] == source["messages"]
    assert credential not in repr(result)
    assert "quota" in result["exchange"]["response"]["error"]["message"]


def test_sqlite_export_is_consistent_and_refuses_overwrite(setup, tmp_path):
    _, store = setup
    record = store.begin(kind="mcp", caller="first", target="tool", request={"x": 1})
    store.finish(record, {"ok": True}, duration_ms=10)
    destination = tmp_path / "exports" / (record["day"] + ".sqlite3")
    store.export_day(record["day"], destination)
    exported = InteractionStore(destination.parent)
    assert exported.query(record["day"], record["id"])["response"] == {"ok": True}
    with pytest.raises(FileExistsError):
        store.export_day(record["day"], destination)


def test_stream_output_and_unsupported_parameters(setup, monkeypatch):
    config, store = setup
    monkeypatch.setattr(
        "subllm.gateway._complete_model_direct",
        lambda *a, **kw: CompletionResponse("done", "zai", "glm-5.3", {}, "stop"),
    )
    payload = {"model": "glm-5.3", "messages": [{"role": "user", "content": "test"}], "stream": True}
    with TestClient(create_app(config, store)) as client:
        r = client.post("/v1/chat/completions", headers=auth(), json=payload)
        assert r.status_code == 200 and "text/event-stream" in r.headers["content-type"]
        assert "data: [DONE]" in r.text and '"content": "done"' in r.text
        assert client.post("/v1/chat/completions", headers=auth(), json={**payload, "tools": []}).status_code == 400
        assert client.post("/v1/chat/completions", headers=auth(OTHER), json=payload).status_code == 403
