"""Configured Unix CLI handshakes keep stdin open during transport failure."""
import json
import os
import selectors
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@contextmanager
def upstream(status=200, malformed=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(405)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_POST(self):
            message = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if status != 200:
                body = b'{"detail":"private upstream diagnostic must stay private"}'
            elif malformed:
                body = b'not-json private upstream diagnostic must stay private'
            else:
                method = message.get("method")
                if method == "initialize":
                    result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                              "serverInfo": {"name": "bridge-fixture", "version": "1"}}
                elif method == "tools/call":
                    result = {"content": [{"type": "text", "text": message["params"]["arguments"]["text"]}]}
                elif method == "resources/read":
                    body = json.dumps({"jsonrpc": "2.0", "id": message["id"],
                                       "error": {"code": -32602, "message": "resource unavailable"}}).encode()
                else:
                    result = {"tools": []}
                if method != "resources/read":
                    body = json.dumps({"jsonrpc": "2.0", "id": message.get("id"), "result": result}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/mcp"
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


@contextmanager
def client(tmp_path, url):
    token = tmp_path / "credential-do-not-print"
    token.write_text("test-" + "x" * 40)
    token.chmod(0o600)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(Path(__file__).parents[1] / "src")
    process = subprocess.Popen([sys.executable, "-m", "subllm.gateway_stdio", "--url", url,
                                "--token-file", str(token)], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    try:
        yield process, token
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=3)


def send(process, method, identifier, params=None):
    if params is None:
        params = {"protocolVersion": "2024-11-05", "capabilities": {},
                  "clientInfo": {"name": "fixture", "version": "1"}} if method == "initialize" else {}
    process.stdin.write((json.dumps({"jsonrpc": "2.0", "id": identifier,
                                    "method": method, "params": params}) + "\n").encode())
    process.stdin.flush()


def receive(process):
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        assert selector.select(timeout=5), "bridge did not answer while stdin stayed open"
        return json.loads(process.stdout.readline())


@pytest.mark.parametrize("status", [401, 403, 500])
def test_upstream_failure_exits_while_client_stdin_stays_open(tmp_path, status):
    with upstream(status=status) as url, client(tmp_path, url) as (process, token):
        send(process, "initialize", 1)
        started = time.monotonic()
        process.wait(timeout=5)
        assert time.monotonic() - started < 5
        assert process.returncode != 0
        assert process.stdout.read() == b""
        error = process.stderr.read().decode()
        assert "MCP transport failed:" in error
        assert "private upstream diagnostic" not in error
        assert token.read_text() not in error
        assert str(token) not in error


def test_unavailable_upstream_exits_without_waiting_for_stdin_eof(tmp_path):
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    with client(tmp_path, f"http://127.0.0.1:{port}/mcp") as (process, token):
        send(process, "initialize", 1)
        process.wait(timeout=5)
        assert process.returncode != 0
        assert process.stdout.read() == b""
        error = process.stderr.read().decode()
        assert "MCP transport failed:" in error
        assert str(token) not in error


def test_malformed_upstream_stays_private_and_exits_promptly(tmp_path):
    with upstream(malformed=True) as url, client(tmp_path, url) as (process, token):
        send(process, "initialize", 1)
        process.wait(timeout=5)
        assert process.returncode != 0
        assert process.stdout.read() == b""
        error = process.stderr.read().decode()
        assert "MCP transport failed:" in error
        assert "private upstream diagnostic" not in error
        assert token.read_text() not in error


def test_valid_initialize_and_tools_list_keep_forwarding(tmp_path):
    with upstream() as url, client(tmp_path, url) as (process, _):
        send(process, "initialize", 1)
        assert receive(process)["result"]["serverInfo"]["name"] == "bridge-fixture"
        send(process, "tools/list", 2)
        assert receive(process) == {"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}
        assert process.poll() is None


def test_large_utf8_messages_and_protocol_errors_keep_forwarding(tmp_path):
    with upstream() as url, client(tmp_path, url) as (process, _):
        send(process, "initialize", 1)
        receive(process)
        text = "zażółć🙂" * 20000
        send(process, "tools/call", 2, {"name": "echo", "arguments": {"text": text}})
        assert receive(process)["result"]["content"][0]["text"] == text
        send(process, "resources/read", 3, {"uri": "fixture://missing"})
        assert receive(process) == {"jsonrpc": "2.0", "id": 3,
                                    "error": {"code": -32602, "message": "resource unavailable"}}
        send(process, "tools/list", 4)
        assert receive(process)["result"] == {"tools": []}
        assert process.poll() is None


def test_client_eof_closes_bridge_cleanly(tmp_path):
    with upstream() as url, client(tmp_path, url) as (process, _):
        send(process, "initialize", 1)
        receive(process)
        process.stdin.close()
        process.stdin = None
        process.wait(timeout=5)
        assert process.returncode == 0
