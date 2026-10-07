from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from subllm.poa import PolicyBus, make_server
from subllm.poa.registry import LIST_ROUTES_REF, VALIDATE_URI


def _start() -> tuple[str, object]:
    bus = PolicyBus()
    server = make_server("127.0.0.1", 0, bus)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    return f"http://127.0.0.1:{port}", server


def _json(method: str, url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def test_http_health_and_query_roundtrip() -> None:
    base, server = _start()
    try:
        health = _json("GET", f"{base}/health")
        assert health["status"] == "ok"
        processes = _json("GET", f"{base}/v1/processes")
        assert processes["home"] == "subactor"
        inspect = _json("POST", f"{base}/v1/inspect", {"process_ref": LIST_ROUTES_REF})
        assert inspect["process_uri"] == "subllm://local/policy/query/list-routes"
        query = _json(
            "POST",
            f"{base}/v1/queries",
            {"schema": "subllm.query/v1", "process_uri": VALIDATE_URI},
        )
        assert query == {"status": "ok"}
        events = _json("GET", f"{base}/v1/events")
        assert events["events"] == []
    finally:
        server.shutdown()
        server.server_close()


def test_http_rejects_unknown_path() -> None:
    base, server = _start()
    try:
        request = Request(f"{base}/v1/shell", method="GET")
        try:
            urlopen(request, timeout=5)
        except HTTPError as exc:
            body = json.loads(exc.read().decode("utf-8"))
            assert exc.code == 404
            assert body["error"]["code"] == "POA-HTTP-404"
        else:
            raise AssertionError("unknown path must fail closed")
    finally:
        server.shutdown()
        server.server_close()


def test_http_usage_detail_endpoint(tmp_path) -> None:
    from subllm.interaction_store import InteractionStore, set_default_interaction_store

    store = InteractionStore(tmp_path / "archive")
    set_default_interaction_store(store)
    record = store.begin(
        kind="llm_attempt",
        caller="http-test",
        target="openai/gpt-5",
        request={"messages": [{"role": "user", "content": "detail-test-prompt"}]},
    )
    store.finish(
        record,
        {"content": "detail-test-response"},
        duration_ms=10,
    )
    base, server = _start()
    try:
        # Missing id returns 400
        req_missing = Request(f"{base}/v1/usage/detail", method="GET")
        try:
            urlopen(req_missing, timeout=5)
        except HTTPError as exc:
            assert exc.code == 400

        # Existing record returns full interaction
        detail = _json("GET", f"{base}/v1/usage/detail?id={record['id']}")
        assert detail["id"] == record["id"]
        assert detail["request"]["messages"] == [{"role": "user", "content": "detail-test-prompt"}]
        assert detail["response"]["content"] == "detail-test-response"
    finally:
        server.shutdown()
        server.server_close()
        set_default_interaction_store(None)


def test_http_usage_detail_endpoint_sqlite_fallback(tmp_path, monkeypatch) -> None:
    from subllm.interaction_store import set_default_interaction_store
    from subllm.usage import record_attempt

    db_path = tmp_path / "usage.sqlite3"
    monkeypatch.setenv("SUBLLM_USAGE_DB", str(db_path))
    set_default_interaction_store(None)

    record_attempt(
        request_id="req-sqlite-fallback-123",
        application="test-app",
        function="chat",
        provider="test-provider",
        model="test-model",
        status="success",
        diagnostic_code=None,
        duration_ms=120,
        usage={"input_tokens": 15, "output_tokens": 25},
    )

    base, server = _start()
    try:
        # Lookup by integer attempt ID 1
        detail = _json("GET", f"{base}/v1/usage/detail?id=1")
        assert detail["id"] == 1
        assert detail["correlation_id"] == "8f5a60a747cf94a0ee93d39c" or len(detail["correlation_id"]) == 24
        assert detail["caller"] == "test-app"
        assert detail["target"] == "test-provider/test-model"
        assert detail["metadata"]["input_tokens"] == 15
        assert detail["metadata"]["output_tokens"] == 25
        assert detail["request"] is None
        assert detail["response"] is None

        # Unknown id returns 404
        req_unknown = Request(f"{base}/v1/usage/detail?id=99999", method="GET")
        try:
            urlopen(req_unknown, timeout=5)
        except HTTPError as exc:
            assert exc.code == 404
    finally:
        server.shutdown()
        server.server_close()

