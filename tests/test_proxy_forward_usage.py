"""SUB-04: raw Ollama forwards are recorded in the usage journal with attribution, counts only."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

import subllm.proxy as proxy
from subllm import make_proxy_server
from subllm.usage import journal_path, query_usage

SECRET_PROMPT = "prompt-text-that-must-never-be-logged"
SECRET_ANSWER = "answer-text-that-must-never-be-logged"


def _upstream(status: int = 200):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            if self.path == "/api/embed":
                body = json.dumps({"embeddings": [[0.1, 0.2]], "prompt_eval_count": 6}).encode()
            elif self.path == "/v1/embeddings":
                usage = {"prompt_tokens": 4, "total_tokens": 4}
                body = json.dumps({"data": [{"embedding": [0.1]}], "usage": usage}).encode()
            elif self.path.startswith("/api/") and request.get("stream"):
                lines = [{"message": {"content": SECRET_ANSWER}, "done": False},
                         {"done": True, "prompt_eval_count": 21, "eval_count": 8}]
                body = "\n".join(json.dumps(line) for line in lines).encode()
            elif self.path.startswith("/api/"):
                body = json.dumps({"message": {"content": SECRET_ANSWER}, "done": True,
                                   "prompt_eval_count": 11, "eval_count": 5}).encode()
            else:
                body = json.dumps({"choices": [{"message": {"content": SECRET_ANSWER}}],
                                   "usage": {"prompt_tokens": 13, "completion_tokens": 3}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


@pytest.fixture
def forward(monkeypatch):
    servers = []

    def start(status: int = 200):
        upstream = _upstream(status)
        monkeypatch.setattr(proxy, "is_upstream_ollama_alive", lambda *a, **k: True)
        monkeypatch.setattr(proxy.adaptive, "policy", lambda *a, **kw: None)
        server = make_proxy_server("127.0.0.1", 0, ollama_upstream=f"http://127.0.0.1:{upstream.server_address[1]}")
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.extend([server, upstream])
        return server

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _post(server, path, payload, headers=None):
    req = Request(f"http://127.0.0.1:{server.server_address[1]}{path}", data=json.dumps(payload).encode(),
                  headers={"Content-Type": "application/json", **(headers or {})}, method="POST")
    try:
        with urlopen(req, timeout=30) as resp:
            return resp.status
    except HTTPError as exc:
        return exc.code


def _attempts():
    return query_usage({"provider": "ollama"})["attempts"]


@pytest.mark.parametrize(("path", "stream", "tokens"), [
    ("/api/chat", False, (11, 5)), ("/api/chat", True, (21, 8)), ("/api/generate", False, (11, 5)),
    ("/v1/chat/completions", False, (13, 3)), ("/api/embed", False, (6, None)), ("/v1/embeddings", False, (4, None)),
])
def test_forward_is_journaled_with_attribution_and_counts(forward, path, stream, tokens):
    server = forward()
    payload = {"model": "qwen2.5-coder:7b", "stream": stream, "prompt": SECRET_PROMPT,
               "messages": [{"role": "user", "content": SECRET_PROMPT}]}
    headers = {"X-Subactor-Application": "autonom", "X-Subactor-Function": "argfill"}
    assert _post(server, path, payload, headers) == 200
    attempt, = _attempts()
    assert (attempt["application"], attempt["function"], attempt["provider"], attempt["model"]) == (
        "autonom", "argfill", "ollama", "qwen2.5-coder:7b")
    assert attempt["status"] == "success"
    assert (attempt["input_tokens"], attempt["output_tokens"]) == tokens
    raw = journal_path().read_bytes()
    assert SECRET_PROMPT.encode() not in raw and SECRET_ANSWER.encode() not in raw


def test_forward_without_headers_is_attributed_to_the_proxy(forward):
    server = forward()
    assert _post(server, "/api/chat", {"model": "d1:3b", "messages": [{"role": "user", "content": "x"}]}) == 200
    attempt, = _attempts()
    assert (attempt["application"], attempt["function"]) == ("subactor-proxy", "forward")


def test_upstream_http_error_is_journaled_as_error(forward):
    server = forward(status=500)
    assert _post(server, "/api/chat", {"model": "d1:3b", "messages": [{"role": "user", "content": "x"}]}) == 500
    attempt, = _attempts()
    assert attempt["status"] == "error" and attempt["diagnostic_code"] == "HTTP_500"
    assert attempt["input_tokens"] is None


@pytest.mark.parametrize(("path", "body", "expected"), [
    ("/api/chat", b'{"done": true, "prompt_eval_count": 4, "eval_count": 2}',
     {"prompt_tokens": 4, "completion_tokens": 2}),
    ("/v1/chat/completions",
     b'data: {"choices": []}\n\ndata: {"usage": {"prompt_tokens": 7, "completion_tokens": 1}}\n\ndata: [DONE]\n',
     {"prompt_tokens": 7, "completion_tokens": 1}),
    ("/api/chat", b"not json", {}), ("/api/chat", b"\xff\xfe", {}),
    ("/api/chat", b'{"done": true, "prompt_eval_count": -1, "eval_count": "2"}', {}),
])
def test_forward_usage_counts(path, body, expected):
    assert proxy.forward_usage_counts(path, body) == expected


def test_parse_strict_json_object_and_correlated_telemetry():
    from subllm.proxy_forward import ForwardJSONError, correlate_forward_telemetry, parse_strict_json_object

    assert parse_strict_json_object(b'{"model":"d1:3b"}') == {"model": "d1:3b"}
    for raw, status in [(b"[1, 2]", 400), (b"null", 400), (b"123", 400), (b'{"a":1,"a":2}', 400),
                        (b'{"x":NaN}', 400), (b"\xff\xfe", 400), (b"{}" * 600_000, 413)]:
        with pytest.raises(ForwardJSONError) as exc_info:
            parse_strict_json_object(raw)
        assert exc_info.value.status == status
    try:
        parse_strict_json_object(f'["{SECRET_PROMPT}"]'.encode())
    except ForwardJSONError as err:
        assert SECRET_PROMPT not in str(err)

    seen = set()
    missing_usage = correlate_forward_telemetry(
        "/api/chat", b'{"message":{"content":"ok"}}',
        client_request_id="req-client-1", proxy_request_id="proxy-9", attempt_id="att-1",
        auth_owner="local-user", application="subactor-autonomy", function="generator", seen_attempts=seen,
    )
    assert missing_usage["usage_known"] is False
    assert missing_usage["input_tokens"] is None and missing_usage["output_tokens"] is None
    assert (missing_usage["client_request_id"], missing_usage["proxy_request_id"], missing_usage["attempt_id"]) == (
        "req-client-1", "proxy-9", "att-1"
    )
    assert correlate_forward_telemetry(
        "/api/chat", b"{}", client_request_id="req-client-1", proxy_request_id="proxy-9",
        attempt_id="att-1", seen_attempts=seen,
    ) is None
