from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from subllm.errors import SubLLMError

from .bus import PolicyBus
from .errors import PoaContractError
from .registry import catalog_document

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}


class PolicyApiHandler(BaseHTTPRequestHandler):
    bus: PolicyBus
    server_version = "subllm-poa/1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        if not self._local_host():
            self._error(421, "POA-HTTP-001", "host is not a local bind")
            return
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._json(200, {"status": "ok", "schema": "subllm.poa.health/v1"})
            return
        if parsed.path == "/v1/processes":
            self._json(200, catalog_document())
            return
        if parsed.path == "/v1/events":
            query = parse_qs(parsed.query)
            run_id = query.get("run_id", [None])[0]
            document: dict[str, Any] = {"schema": "subllm.query/v1", "process_uri": "subllm://local/policy/query/events"}
            if run_id:
                document["run_id"] = run_id
            self._dispatch_query(document)
            return
        self._error(404, "POA-HTTP-404", "path is not registered")

    def do_POST(self) -> None:
        if not self._local_host():
            self._error(421, "POA-HTTP-001", "host is not a local bind")
            return
        payload = self._read_json()
        if payload is None:
            return
        path = urlparse(self.path).path
        try:
            if path == "/v1/inspect":
                process_ref = payload.get("process_ref") if isinstance(payload, dict) else None
                if not isinstance(process_ref, str):
                    raise PoaContractError("POA-DOC-001", "inspect request is not closed")
                self._json(200, self.bus.inspect(process_ref))
                return
            if path == "/v1/plan":
                if not isinstance(payload, dict):
                    raise PoaContractError("POA-DOC-001", "plan request is not closed")
                command = {
                    "schema": "subllm.command/v1",
                    "process_uri": "subllm://local/policy/command/create-plan",
                    "process_ref": payload.get("process_ref"),
                    "input_ref": payload.get("input_ref"),
                    "input_sha256": payload.get("input_sha256"),
                    "subject": payload.get("subject") or "service:subllm-http",
                    "idempotency_key": payload.get("idempotency_key") or "http.plan.default1",
                }
                self._json(200, self.bus.command(command))
                return
            if path == "/v1/queries":
                self._dispatch_query(payload)
                return
            if path == "/v1/commands":
                self._json(200, self.bus.command(payload))
                return
        except PoaContractError as exc:
            self._error(400, exc.code, str(exc))
            return
        except SubLLMError:
            self._error(422, "SUBLLM-POLICY-001", "policy request was rejected")
            return
        self._error(404, "POA-HTTP-404", "path is not registered")

    def _dispatch_query(self, payload: Any) -> None:
        try:
            self._json(200, self.bus.query(payload))
        except PoaContractError as exc:
            self._error(400, exc.code, str(exc))
        except SubLLMError:
            self._error(422, "SUBLLM-POLICY-001", "policy request was rejected")

    def _local_host(self) -> bool:
        host = (self.headers.get("Host") or "").split(":", 1)[0].strip().lower()
        return host in ALLOWED_HOSTS

    def _read_json(self) -> Any | None:
        length = self.headers.get("Content-Length")
        if length is None:
            self._error(400, "POA-HTTP-001", "content length is required")
            return None
        try:
            size = int(length)
        except ValueError:
            self._error(400, "POA-HTTP-001", "content length is invalid")
            return None
        if size < 2 or size > 16384:
            self._error(400, "POA-HTTP-001", "request body size is outside bounds")
            return None
        try:
            return json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(400, "POA-HTTP-001", "request body is not JSON")
            return None

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        self._json(status, {"error": {"code": code, "message": message}})


def make_server(host: str, port: int, bus: PolicyBus | None = None) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise PoaContractError("POA-HTTP-001", "server bind is not local")
    handler = type("BoundPolicyApiHandler", (PolicyApiHandler,), {"bus": bus or PolicyBus()})
    return ThreadingHTTPServer((host, port), handler)


def serve(host: str = "127.0.0.1", port: int = 8788, bus: PolicyBus | None = None) -> None:
    server = make_server(host, port, bus)
    try:
        server.serve_forever()
    finally:
        server.server_close()
