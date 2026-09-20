"""Authenticated single endpoint for policy-routed LLM, MCP and private history."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time
import tomllib
from contextlib import AsyncExitStack, asynccontextmanager
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlparse

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route

from .client_routes import complete
from .errors import SubLLMError
from .gateway_bus import GatewayPolicyBus
from .gateway_diagnostics import diagnostic
from .gateway_mcp import MCPBridge
from .interaction_context import ACTIVE_ARCHIVE
from .interaction_store import InteractionStore, utc_now
from .policy import MODELS, ROUTES
from .proxy import _complete_model_direct
from .usage import query_usage

LOG = logging.getLogger(__name__)


class ArchiveAdmissionError(RuntimeError):
    pass


NAME = re.compile(r"[a-z][a-z0-9_-]{0,63}\Z")


def _legacy_usage_id(attempt_id: int) -> str:
    return hashlib.sha256(f"subllm-usage:{attempt_id}".encode()).hexdigest()[:32]


def _legacy_usage_record(attempt: dict) -> dict:
    """Normalize metadata-only transport telemetry into the private history view."""
    timestamp = attempt["timestamp"]
    return {
        "id": _legacy_usage_id(attempt["id"]),
        "day": timestamp[:10],
        "started_at": timestamp,
        "finished_at": timestamp,
        "duration_ms": attempt["duration_ms"],
        "kind": "llm_attempt",
        "caller": attempt["application"],
        "target": f"{attempt['provider']}/{attempt['model']}",
        "direction": "client_to_server",
        "correlation_id": attempt["request_id"],
        "status": attempt["status"],
        "diagnostic": {"code": attempt["diagnostic_code"]} if attempt["diagnostic_code"] else None,
        "metadata": {
            "provider": attempt["provider"],
            "model": attempt["model"],
            "function": attempt["function"],
            "input_tokens": attempt["input_tokens"],
            "output_tokens": attempt["output_tokens"],
            "source": "transport-telemetry",
            "capture": "metadata-only",
        },
        "capture": "metadata-only",
        "source": "usage.sqlite3",
        "request": {
            "captured": False,
            "reason": "Wywołanie ominęło gateway; dostępne są tylko metadane transportu.",
        },
        "response": {
            "captured": False,
            "reason": "Skieruj klienta przez /v1/chat/completions, aby archiwizować żądanie i odpowiedź.",
        },
    }


def _legacy_usage_records(database, day, *, status=None, before=None, limit=500, caller=None):
    if not database:
        return []
    filters = {"limit": 500}
    if status:
        filters["status"] = status
    try:
        attempts = query_usage(filters, database).get("attempts", [])
    except Exception:
        LOG.warning("SUBLLM-USAGE-READ: legacy metadata unavailable")
        return []
    rows = []
    for attempt in attempts:
        record = _legacy_usage_record(attempt)
        if (
            record["day"] != day
            or (caller and record["caller"] != caller)
            or (before and record["started_at"] >= before)
        ):
            continue
        rows.append(record)
    rows.sort(key=lambda row: (row["started_at"], row["id"]), reverse=True)
    return rows[:limit]


def validate_config(config):
    if not config.get("clients"):
        raise ValueError("At least one authenticated client is required")
    tokens = set()
    for name, client in config["clients"].items():
        if not NAME.fullmatch(name):
            raise ValueError("Invalid client name")
        token = os.environ[client["token_env"]]
        if len(token) < 32 or token in tokens:
            raise ValueError("Client tokens must be distinct and at least 32 characters")
        tokens.add(token)
        if set(client.get("mcp", [])) - set(config.get("mcp", {})):
            raise ValueError("Client refers to an unregistered MCP server")
    for name, upstream in config.get("mcp", {}).items():
        if not NAME.fullmatch(name) or ("command" in upstream) == ("url" in upstream):
            raise ValueError("MCP requires a valid name and exactly one command or URL")
        if "url" in upstream:
            url = urlparse(upstream["url"])
            if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query:
                raise ValueError("MCP URL must be HTTP(S) without embedded credentials or query")
    return config


class GatewayGuard:
    def __init__(self, app, config):
        self.app, self.config = app, config

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        host = request.headers.get("host", "")
        if host not in self.config.get("allowed_hosts", ["127.0.0.1:8789", "localhost:8789"]):
            return await JSONResponse({"error": "Unregistered host"}, 421)(scope, receive, send)
        origin = request.headers.get("origin")
        if origin and origin != f"{scope['scheme']}://{host}":
            return await JSONResponse({"error": "Cross-origin access denied"}, 403)(scope, receive, send)
        public = scope["path"] in {"/", "/assets/gateway.js", "/assets/gateway.css", "/favicon.ico"}
        principal = None
        auth = request.headers.get("authorization", "")
        if auth.startswith("Bearer "):
            for name, client in self.config["clients"].items():
                if hmac.compare_digest(auth[7:], os.environ[client["token_env"]]):
                    principal = name
        if not principal and not public:
            return await JSONResponse({"error": "Bearer credential required"}, 401)(scope, receive, send)
        scope.setdefault("state", {})["principal"] = principal
        if request.method == "POST":
            body = bytearray()
            while True:
                part = await receive()
                if part["type"] == "http.disconnect":
                    return
                body.extend(part.get("body", b""))
                if len(body) > 10_000_000:
                    return await JSONResponse({"error": "Body exceeds 10 MB"}, 413)(scope, receive, send)
                if not part.get("more_body"):
                    break
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": bytes(body), "more_body": False}
                return await receive()

            inbound = replay
        else:
            inbound = receive

        async def headers(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"x-content-type-options", b"nosniff"),
                        (b"content-security-policy", b"default-src 'self'; frame-ancestors 'none'; base-uri 'none'"),
                    ]
                )
            await send(message)

        await self.app(scope, inbound, headers)


def create_app(config, store=None):
    config = validate_config(config)
    legacy_usage_database = config.get("usage_database")
    store = store or InteractionStore(
        Path(config["archive_directory"]).expanduser().absolute(),
        os.environ.get(config.get("postgres_dsn_env", "SUBLLM_GATEWAY_DATABASE_URL")),
    )
    bus = GatewayPolicyBus(store)
    managers = {}
    admission_locks = {}
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=config.get("allowed_hosts", ["127.0.0.1:8789"]),
        allowed_origins=[],
    )
    for caller, client in config["clients"].items():
        for name in client.get("mcp", []):
            bridge = MCPBridge(name, config["mcp"][name], store, caller, bus)
            managers[caller, name] = StreamableHTTPSessionManager(bridge, security_settings=security)
            admission_locks[caller, name] = asyncio.Lock()

    @asynccontextmanager
    async def lifespan(app):
        async with AsyncExitStack() as stack:
            for manager in managers.values():
                await stack.enter_async_context(manager.run())
            yield

    async def mcp(scope, receive, send):
        name = scope["path"].rstrip("/").rsplit("/", 1)[-1]
        manager = managers.get((scope["state"]["principal"], name))
        if manager is None:
            return await JSONResponse({"error": "MCP server not granted"}, 403)(scope, receive, send)
        request = Request(scope)
        if not request.headers.get("mcp-session-id"):
            if request.method != "POST":
                return await JSONResponse({"error": "Initialize a session first"}, 400)(scope, receive, send)
            # Bound subprocess ownership. SDK implementation is pinned and integration-tested.
            async with admission_locks[scope["state"]["principal"], name]:
                if len(manager._server_instances) >= config.get("max_sessions_per_server", 16):
                    return await JSONResponse({"error": "MCP session limit reached"}, 429)(scope, receive, send)
                return await manager.handle_request(scope, receive, send)
        await manager.handle_request(scope, receive, send)

    async def history(request):
        client = config["clients"][request.state.principal]
        params = dict(request.query_params)
        if set(params) - {"day", "id", "kind", "status", "limit", "before"}:
            return JSONResponse({"error": "Unknown filter"}, 400)
        try:
            day = params.pop("day", utc_now()[:10])
            record_id = params.pop("id", None)
            kind = params.pop("kind", None)
            status = params.pop("status", None)
            limit = int(params.pop("limit", "100"))
            before = params.pop("before", None)
            read_all = client.get("read_all", False)
            visible_caller = None if read_all else request.state.principal

            def query_gateway_rows(query_kind=None):
                return bus.interaction_query(
                    day=day,
                    caller=request.state.principal,
                    read_all=read_all,
                    kind=query_kind,
                    status=status,
                    limit=limit,
                    before=before,
                )

            if record_id:
                result = bus.interaction_query(
                    day=day,
                    record_id=record_id,
                    caller=request.state.principal,
                    read_all=read_all,
                    kind=kind,
                    status=status,
                    limit=limit,
                    before=before,
                )
                if result is None and kind in (None, "llm", "llm_attempt"):
                    legacy_rows = _legacy_usage_records(
                        legacy_usage_database,
                        day,
                        status=status,
                        before=before,
                        caller=visible_caller,
                    )
                    result = next((row for row in legacy_rows if row["id"] == record_id), None)
            else:
                if kind == "llm":
                    result = query_gateway_rows("llm") + query_gateway_rows("llm_attempt")
                else:
                    result = query_gateway_rows(kind)
                if kind in (None, "llm", "llm_attempt"):
                    result.extend(
                        {
                            key: value
                            for key, value in row.items()
                            if key not in {"request", "response"}
                        }
                        for row in _legacy_usage_records(
                            legacy_usage_database,
                            day,
                            status=status,
                            before=before,
                            limit=limit,
                            caller=visible_caller,
                        )
                    )
                    result.sort(key=lambda row: (row["started_at"], row["id"]), reverse=True)
                    result = result[:limit]
            return JSONResponse({"data": result})
        except ValueError:
            return JSONResponse({"error": "Invalid archive query"}, 400)
        except Exception:
            LOG.error("SUBLLM-ARCHIVE-READ: archive unavailable")
            return JSONResponse({"error": "Archive unavailable"}, 503)

    async def models(request):
        return JSONResponse(
            {
                "object": "list",
                "data": [
                    {"id": name, "object": "model", "owned_by": "subllm"}
                    for name in [*(m for m in MODELS if not MODELS[m].forbidden), *(f"{a}/{f}" for a, f in ROUTES)]
                ],
            }
        )

    async def completion(request):
        caller = request.state.principal
        if not config["clients"][caller].get("llm", False):
            return JSONResponse({"error": "LLM access not granted"}, 403)
        try:
            payload = await request.json()
            if (
                not isinstance(payload, dict)
                or set(payload) - {"model", "messages", "stream", "response_format"}
                or not isinstance(payload.get("model"), str)
                or not isinstance(payload.get("messages"), list)
                or not payload["messages"]
                or type(payload.get("stream", False)) is not bool
            ):
                raise ValueError("Expected model, messages, optional stream and response_format")
            model = payload["model"]
            if model not in MODELS and model not in {f"{a}/{f}" for a, f in ROUTES}:
                raise ValueError("Model or route is not registered")
            if "response_format" in payload and model in MODELS:
                raise ValueError("response_format requires a named application/function route")
        except (ValueError, UnicodeDecodeError):
            return JSONResponse({"error": "Invalid request or unsupported generation parameter"}, 400)

        def invoke():
            try:
                record = store.begin(kind="llm", caller=caller, target=model, request=payload)
                bus.record_gateway_exchange(record)
            except Exception:
                raise ArchiveAdmissionError from None
            started = time.monotonic()
            capture = ACTIVE_ARCHIVE.set((store, record))
            try:
                if model in MODELS:
                    response = _complete_model_direct(
                        model,
                        payload["messages"],
                        application="subactor-proxy",
                        function="chat",
                        timeout_seconds=120,
                        request_id=record["id"],
                    )
                else:
                    app, function = model.split("/", 1)
                    response = complete(
                        app,
                        function,
                        payload["messages"],
                        timeout_seconds=120,
                        response_format=payload.get("response_format"),
                        request_id=record["id"],
                    )
                result = {
                    "id": "chatcmpl-" + record["id"],
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": response.model,
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": response.content},
                            "finish_reason": response.finish_reason or "stop",
                        }
                    ],
                    "usage": dict(response.usage),
                }
                info, status = None, 200
                metadata = {"provider": response.provider, "model": response.model}
            except Exception as exc:
                code = getattr(exc, "diagnostic_code", None)
                info = diagnostic(
                    "SUBLLM-UPSTREAM-TIMEOUT" if isinstance(exc, TimeoutError) else "SUBLLM-LLM-EXECUTION"
                )
                result = {"error": {"code": code or info["code"], "message": info["meaning"]}}
                # Exception detail belongs only to the authenticated private archive.
                from .credential_env import credential_names, merged_environment

                detail = str(exc)[:4000]
                try:
                    environment = merged_environment()
                except SubLLMError:
                    environment = {}
                for key in credential_names():
                    if environment.get(key):
                        detail = detail.replace(environment[key], "[credential removed]")
                metadata, status = {"exception_type": type(exc).__name__, "error_detail": detail}, 502
                if not isinstance(exc, (SubLLMError, TimeoutError)):
                    LOG.error("SUBLLM-LLM-EXECUTION: unexpected upstream failure")
            finally:
                ACTIVE_ARCHIVE.reset(capture)
            elapsed = int((time.monotonic() - started) * 1000)
            if info:
                info["durationMs"] = elapsed
            archived = True
            try:
                store.finish(record, result, duration_ms=elapsed, diagnostic=info, metadata=metadata)
            except Exception:
                archived = False
                LOG.error("SUBLLM-ARCHIVE-WRITE: result returned; archive entry remains pending")
            return result, status, record, archived

        try:
            result, status, record, archived = await asyncio.to_thread(invoke)
        except ArchiveAdmissionError:
            return JSONResponse({"error": "Archive unavailable; upstream call was not started"}, 503)
        except Exception:
            return JSONResponse({"error": "Execution state uncertain; inspect interaction archive before retry"}, 500)
        headers = {
            "X-SubLLM-Interaction": f"{record['day']}/{record['id']}",
            "X-SubLLM-Archive-Status": "complete" if archived else "pending",
        }
        if payload.get("stream") and status == 200:
            # Compatibility stream after the routed completion; no false claim of live upstream tokens.
            chunk = {k: v for k, v in result.items() if k != "choices"}
            chunk["object"] = "chat.completion.chunk"

            async def stream():
                yield (
                    "data: "
                    + json.dumps(
                        {
                            **chunk,
                            "choices": [{"index": 0, "delta": result["choices"][0]["message"], "finish_reason": None}],
                        }
                    )
                    + "\n\n"
                )
                yield (
                    "data: "
                    + json.dumps(
                        {
                            **chunk,
                            "choices": [
                                {"index": 0, "delta": {}, "finish_reason": result["choices"][0]["finish_reason"]}
                            ],
                        }
                    )
                    + "\n\n"
                )
                yield "data: [DONE]\n\n"

            return StreamingResponse(stream(), media_type="text/event-stream", headers=headers)
        return JSONResponse(result, status, headers=headers)

    async def asset(request):
        path = request.url.path
        if path == "/favicon.ico":
            return Response(
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
                '<rect width="32" height="32" rx="6" fill="#2457cf"/>'
                '<text x="7" y="24" fill="white" font-size="24">S</text></svg>',
                media_type="image/svg+xml",
            )
        name = "gateway.html" if path == "/" else path.rsplit("/", 1)[-1]
        return FileResponse(str(files("subllm").joinpath("assets", name)))

    app = Starlette(
        routes=[
            Route("/", asset),
            Route("/favicon.ico", asset),
            Route("/assets/gateway.js", asset),
            Route("/assets/gateway.css", asset),
            Route("/v1/interactions", history),
            Route("/v1/models", models),
            Route("/v1/chat/completions", completion, methods=["POST"]),
            Mount("/mcp", app=mcp),
        ],
        lifespan=lifespan,
    )
    return GatewayGuard(app, config)


def main():
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8789)
    parser.add_argument("--export-day")
    parser.add_argument("--export-to", type=Path)
    parser.add_argument("--ssl-certfile")
    parser.add_argument("--ssl-keyfile")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "::1", "localhost"} and not (args.ssl_certfile and args.ssl_keyfile):
        parser.error("LAN bind requires TLS certificate and key")
    config = tomllib.loads(args.config.read_text())
    if args.export_day:
        if not args.export_to:
            parser.error("--export-day requires --export-to")
        store = InteractionStore(
            Path(config["archive_directory"]).expanduser().absolute(),
            os.environ.get(config.get("postgres_dsn_env", "SUBLLM_GATEWAY_DATABASE_URL")),
        )
        store.export_day(args.export_day, args.export_to)
        return
    uvicorn.run(
        create_app(config),
        host=args.host,
        port=args.port,
        access_log=False,
        ssl_certfile=args.ssl_certfile,
        ssl_keyfile=args.ssl_keyfile,
    )


if __name__ == "__main__":
    main()
