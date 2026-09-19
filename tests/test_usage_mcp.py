from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from subllm.mcp import dispatch
from subllm.poa import PolicyBus, make_server
from subllm.poa.errors import PoaContractError
from subllm.poa.registry import RECORD_USAGE_URI
from subllm.usage import journal_path, query_usage
from subllm.usage_dsl import ask, execute


def event():
    return {
        "schema": "subllm.command/v1",
        "process_uri": RECORD_USAGE_URI,
        "subject": "service:validator-agent",
        "idempotency_key": "usage.1234567890",
        "attempt": {
            "request_id": "request-1",
            "application": "validator-agent",
            "function": "review",
            "provider": "zai",
            "model": "glm-5.3",
            "status": "success",
            "duration_ms": 42,
            "usage": {"input_tokens": 12, "output_tokens": 7},
        },
    }


def test_ingestion_and_all_read_interfaces_are_identical():
    bus = PolicyBus()
    assert bus.command(event())["accepted"]
    assert len(bus.store.events()) == 1
    assert bus.store.events()[0]["schema"] == "poa.event/v1"
    assert PolicyBus().command(event())["duplicate"]  # persistent deduplication across process lifetime
    dsl = execute("usage.list provider=zai", bus)
    assert dsl == ask("pokaż logi z.ai", bus)
    result = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "execute_dsl", "arguments": {"command": "usage.list provider=zai"}},
        },
        bus,
    )
    assert result["result"]["structuredContent"] == dsl
    assert dsl["data"]["summary"]["attempts"] == 1
    assert len(bus.store.events()) == 1
    assert "event_key" not in dsl["data"]["attempts"][0]


@pytest.mark.parametrize(
    "field,value",
    [
        ("prompt", "SECRET"),
        ("usage", {"input_tokens": "secret"}),
        ("duration_ms", -1),
        ("status", "ignored"),
        ("diagnostic_code", "response contains secret!"),
        ("application", ["invalid"]),
        ("usage", {"secret": "do not persist"}),
    ],
)
def test_ingest_rejects_unknown_fields_and_payloads(field, value):
    payload = event()
    payload["attempt"][field] = value
    with pytest.raises(PoaContractError):
        PolicyBus().command(payload)
    assert not journal_path().exists()


def test_ingest_reports_unavailable_storage(monkeypatch, tmp_path):
    bad = tmp_path / "file"
    bad.write_text("not a directory")
    monkeypatch.setenv("SUBLLM_USAGE_DB", str(bad / "db"))
    with pytest.raises(PoaContractError, match="temporarily unavailable"):
        PolicyBus().command(event())


@pytest.mark.parametrize(
    "command", ["delete all", "usage.delete", "usage.list limit=1 limit=2", "usage.list unknown_filter=abc"]
)
def test_dsl_cannot_mutate_or_expand_scope(command):
    with pytest.raises(PoaContractError):
        execute(command, PolicyBus())
    assert not journal_path().exists()


def test_stdio_protocol_and_query_dont_write():
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "resources/read", "params": {"uri": "schema://current"}},
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "nl_ask", "arguments": {"question": "show api usage"}},
        },
    ]
    run = subprocess.run(
        [sys.executable, "-m", "subllm.cli", "mcp"],
        input="\n".join(json.dumps(m) for m in messages) + "\n",
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).parents[1] / "src")},
        check=True,
    )
    output = [json.loads(row) for row in run.stdout.splitlines()]
    assert len(output) == 4
    assert output[0]["result"]["protocolVersion"] == "2025-06-18"
    assert {x["name"] for x in output[1]["result"]["tools"]} == {"nl_ask", "execute_dsl", "describe_grammar"}
    assert output[-1]["result"]["structuredContent"]["data"]["storage"] == "empty"
    assert not journal_path().exists()


def test_http_ingest_mcp_and_rest_parity():
    server = make_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"

    def post(path, payload, **headers):
        return urlopen(
            Request(
                base + path,
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    **headers,
                },
            ),
            timeout=5,
        )

    try:
        with post("/v1/commands", event()) as response:
            assert json.load(response)["accepted"]
        with post("/api/v1/dsl", {"command": "usage.list"}) as response:
            dsl = json.load(response)
        with post(
            "/mcp",
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "nl_ask", "arguments": {"question": "pokaż logi"}},
            },
        ) as response:
            assert json.load(response)["result"]["structuredContent"] == dsl
        with post("/mcp", {"jsonrpc": "2.0", "method": "notifications/initialized"}) as response:
            assert response.status == 202 and response.read() == b""
        with pytest.raises(HTTPError) as e:
            post("/v1/commands", event(), Origin="https://evil.example")
        assert e.value.code == 403
        with pytest.raises(HTTPError) as e:
            post("/mcp", {}, **{"MCP-Protocol-Version": "invalid"})
        assert e.value.code == 400
        with pytest.raises(HTTPError) as e:
            urlopen(base + "/mcp", timeout=5)
        assert e.value.code == 405
        assert query_usage({})["summary"]["attempts"] == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
