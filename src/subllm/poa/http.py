from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from typing import Any
from urllib.parse import parse_qs, urlparse

from subllm.errors import SubLLMError

from .bus import PolicyBus
from .errors import PoaContractError
from .registry import USAGE_URI, catalog_document

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
        if parsed.path in {"/", "/assets/usage.css", "/assets/usage.js", "/v1/usage", "/v1/usage/detail"}:
            if not self._same_origin():
                self._error(403, "USAGE-ORIGIN-001", "Cross-origin access is not allowed")
                return
            if parsed.path == "/v1/usage/detail":
                from subllm.usage import query_interaction_detail

                query = parse_qs(parsed.query)
                record_id = query.get("id", [None])[0] or query.get("record_id", [None])[0]
                if not record_id:
                    self._error(400, "USAGE-PARAM-001", "Missing id parameter")
                    return
                detail = query_interaction_detail(record_id)
                if detail is None:
                    self._error(404, "USAGE-NOT-FOUND-001", "Interaction detail not found")
                    return
                self._json(200, detail)
                return
            if parsed.path == "/v1/usage":
                from subllm.usage import FILTERS

                query = parse_qs(parsed.query, keep_blank_values=True)
                if set(query) - FILTERS:
                    self._error(400, "USAGE-FILTER-001", "Unknown usage filter")
                    return
                if any(len(value) != 1 for value in query.values()):
                    self._error(400, "USAGE-FILTER-001", "Duplicate usage filter")
                    return
                self._dispatch_query({"schema": "subllm.query/v1", "process_uri": USAGE_URI,
                                      **{key: value[0] for key, value in query.items()}})
                return
            name, content_type = {
                "/": ("usage.html", "text/html; charset=utf-8"),
                "/assets/usage.css": ("usage.css", "text/css; charset=utf-8"),
                "/assets/usage.js": ("usage.js", "text/javascript; charset=utf-8"),
            }[parsed.path]
            body = files("subllm").joinpath("assets", name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; "
                             "base-uri 'none'; form-action 'self'")
            self.end_headers()
            self.wfile.write(body)
            return
        if parsed.path == "/mcp":
            self._error(405, "MCP-HTTP-001", "Use POST; server does not provide an SSE stream")
            return
        if parsed.path == "/api/v1/schema":
            from subllm.usage_dsl import grammar
            self._json(200, grammar())
            return
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
        if not self._same_origin():
            self._error(403, "USAGE-ORIGIN-001", "Cross-origin access is not allowed")
            return
        payload = self._read_json()
        if payload is None:
            return
        path = urlparse(self.path).path
        try:
            if path == "/mcp":
                from subllm.mcp import VERSIONS, dispatch
                if self.headers.get("MCP-Protocol-Version", "2025-03-26") not in VERSIONS:
                    self._error(400, "MCP-VERSION-001", "Unsupported MCP version")
                    return
                response = dispatch(payload, self.bus)
                if response is None:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self._json(200, response)
                return
            if path in {"/api/v1/dsl", "/api/v1/query"}:
                from subllm.usage_dsl import ask, execute
                key = "command" if path.endswith("dsl") else "question"
                if not isinstance(payload, dict) or set(payload) != {key}:
                    raise PoaContractError("USAGE-DSL-001", "Expected a closed DSL/query request")
                self._json(200, (execute if key == "command" else ask)(payload[key], self.bus))
                return
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
            self._error(503 if exc.code == "USAGE-STORAGE-001" else 400, exc.code, str(exc))
        except SubLLMError:
            self._error(422, "SUBLLM-POLICY-001", "policy request was rejected")

    def _same_origin(self) -> bool:
        origin = self.headers.get("Origin")
        return (self.headers.get("Sec-Fetch-Site") != "cross-site"
                and (origin is None or origin == "http://" + (self.headers.get("Host") or "")))

    def _local_host(self) -> bool:
        try:
            host = urlparse("http://" + (self.headers.get("Host") or "")).hostname
            return host in ALLOWED_HOSTS
        except ValueError:
            return False

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
