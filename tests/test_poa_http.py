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
