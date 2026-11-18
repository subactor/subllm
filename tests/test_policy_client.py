"""HEY-06: shared client for the central routing contract (replaces per-consumer HTTP code)."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from subllm import policy_client as pc
from subllm.poa.canonical import digest_document


def _contract(**overrides):
    body = {"schema": "subllm.routing-contract/v1", "version": 1, "application": "subactor-proxy",
            "function": "completion", "candidates": [{"provider": "zai", "model": "glm-5.3", "priority": 0}],
            "execution": {"max_attempts": 6, "failover_enabled": True}}
    body.update(overrides)
    return {**body, "sha256": digest_document(body)}


@pytest.fixture
def server():
    state = {"requests": [], "body": _contract(), "status": 200, "delay": 0.0}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):  # noqa: N802
            state["requests"].append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            time.sleep(state["delay"] if self.path.endswith("/slow") else 0)
            raw = state["body"] if isinstance(state["body"], bytes) else json.dumps(state["body"]).encode()
            self.send_response(state["status"])
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    pc.clear_routing_contract_cache()
    yield f"http://127.0.0.1:{srv.server_port}/v1/queries", state
    pc.clear_routing_contract_cache()
    srv.shutdown()
    srv.server_close()


def test_fetches_verified_contract_with_the_policy_query_and_caches_it(server):
    endpoint, state = server
    assert pc.fetch_routing_contract(endpoint, "subactor-proxy", "completion") == state["body"]
    pc.fetch_routing_contract(endpoint, "subactor-proxy", "completion")
    assert len(state["requests"]) == 1
    assert state["requests"][0][1] == {"schema": "subllm.query/v1",
                                       "process_uri": "subllm://local/policy/query/export-routing-contract",
                                       "application": "subactor-proxy", "function": "completion"}


def test_cache_expires(server):
    endpoint, state = server
    pc.fetch_routing_contract(endpoint, "subactor-proxy", "completion", cache_seconds=0)
    pc.fetch_routing_contract(endpoint, "subactor-proxy", "completion", cache_seconds=0)
    assert len(state["requests"]) == 2


@pytest.mark.parametrize(("body", "message"), [
    ({**_contract(), "extra": 1}, "fields"),
    (_contract(version=2), "version"),
    (_contract(function="other"), "profile mismatch"),
    (_contract(candidates=[]), "no candidates"),
    ({**_contract(), "sha256": "0" * 64}, "checksum mismatch"),
    (b"not json", "not JSON"),
    (b"x" * (pc.MAX_CONTRACT_BYTES + 1), "exceeds 1 MiB"),
])
def test_invalid_contracts_raise_value_errors(server, body, message):
    endpoint, state = server
    state["body"] = body
    with pytest.raises(pc.InvalidRoutingContract, match=message) as caught:
        pc.fetch_routing_contract(endpoint, "subactor-proxy", "completion")
    assert isinstance(caught.value, ValueError)


def test_http_error_and_unreachable_endpoint_raise_runtime_errors(server):
    endpoint, state = server
    state["status"] = 503
    with pytest.raises(pc.PolicyEndpointUnavailable, match="HTTP 503") as caught:
        pc.fetch_routing_contract(endpoint, "subactor-proxy", "completion")
    assert isinstance(caught.value, RuntimeError)
    with pytest.raises(pc.PolicyEndpointUnavailable, match="unavailable"):
        pc.fetch_routing_contract("http://127.0.0.1:9/v1/queries", "subactor-proxy", "completion", timeout=0.5)


def test_non_http_endpoint_is_rejected():
    with pytest.raises(pc.InvalidRoutingContract, match="http"):
        pc.fetch_routing_contract("file:///etc/passwd", "subactor-proxy", "completion")


def test_a_slow_profile_does_not_block_another_endpoint(server):
    endpoint, state = server
    state["delay"] = 1.5
    slow = threading.Thread(target=lambda: pc.fetch_routing_contract(endpoint + "/slow", "subactor-proxy",
                                                                     "completion"))
    slow.start()
    time.sleep(0.2)
    started = time.monotonic()
    assert pc.fetch_routing_contract(endpoint, "subactor-proxy", "completion")["function"] == "completion"
    assert time.monotonic() - started < 1.0
    slow.join()
