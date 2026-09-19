"""Transparent MCP message bridge; official SDK owns HTTP and stdio framing."""

from __future__ import annotations

import contextlib
import logging
import os
import time

import anyio
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage

from .gateway_diagnostics import diagnostic, rpc_diagnostic, transport_diagnostic

LOG = logging.getLogger(__name__)


class MCPBridge:
    def __init__(self, name, config, store, caller, bus):
        self.name, self.config, self.store, self.caller, self.bus = name, config, store, caller, bus

    def create_initialization_options(self):
        # Initialization is forwarded, including upstream capabilities and version.
        return None

    @contextlib.asynccontextmanager
    async def upstream(self):
        if "command" in self.config:
            env = {key: os.environ[value] for key, value in self.config.get("env_from", {}).items()}
            params = StdioServerParameters(
                command=self.config["command"], args=self.config.get("args", []), env=env, cwd=self.config.get("cwd")
            )
            # Raw stderr may contain secrets. It is not an operational event stream.
            with open(os.devnull, "w") as errlog:
                async with stdio_client(params, errlog=errlog) as streams:
                    yield streams
        else:
            headers = {key: os.environ[value] for key, value in self.config.get("headers_from", {}).items()}
            async with streamablehttp_client(self.config["url"], headers=headers) as streams:
                yield streams[:2]

    async def run(self, downstream_read, downstream_write, options, **kwargs):
        pending = {}

        def observe(message, direction):
            obj = message.message.model_dump(mode="json", by_alias=True, exclude_none=True)
            request_id = obj.get("id")
            key = (direction, type(request_id).__name__, request_id)
            if "method" in obj:
                record = self.store.begin(
                    kind="mcp", caller=self.caller, target=self.name, request=obj, direction=direction
                )
                self.bus.record_gateway_exchange(record)
                if request_id is not None:
                    if key in pending:
                        raise ValueError("Duplicate pending JSON-RPC id")
                    pending[key] = (record, time.monotonic())
                else:
                    self.store.finish(record, None, metadata={"notification": True})
            else:
                reverse = "server_to_client" if direction == "client_to_server" else "client_to_server"
                entry = pending.pop((reverse, type(request_id).__name__, request_id), None)
                if entry:
                    record, started = entry
                    elapsed = int((time.monotonic() - started) * 1000)
                    info = rpc_diagnostic(obj)
                    if info:
                        info["durationMs"] = elapsed
                    try:
                        self.store.finish(record, obj, duration_ms=elapsed, diagnostic=info)
                    except Exception:
                        # Deliver an already produced tool result; do not invite a side-effect retry.
                        LOG.error("SUBLLM-ARCHIVE-WRITE: MCP response returned; archive remains pending")
                else:
                    record = self.store.begin(
                        kind="mcp", caller=self.caller, target=self.name, request=None, direction=direction
                    )
                    self.store.finish(record, obj, metadata={"unmatched_response": True})

        async def pump(source, destination, direction, group):
            try:
                async for message in source:
                    if isinstance(message, Exception):
                        raise message
                    await anyio.to_thread.run_sync(observe, message, direction)
                    await destination.send(message)
            finally:
                group.cancel_scope.cancel()

        first = await downstream_read.receive()
        if isinstance(first, Exception):
            return
        await anyio.to_thread.run_sync(observe, first, "client_to_server")
        failure = None
        try:
            with anyio.fail_after(self.config.get("session_lifetime_seconds", 3600)):
                async with self.upstream() as (up_read, up_write), anyio.create_task_group() as group:
                    await up_write.send(first)
                    group.start_soon(pump, downstream_read, up_write, "client_to_server", group)
                    group.start_soon(pump, up_read, downstream_write, "server_to_client", group)
        except Exception as error:
            failure = transport_diagnostic(error)
            # Never let the SDK print arbitrary provider exception text or payloads.
            LOG.error("%s: MCP session failed", failure["code"])
            for record, _ in pending.values():
                if record["direction"] == "client_to_server":
                    reply = JSONRPCMessage.model_validate(
                        {
                            "jsonrpc": "2.0",
                            "id": record["request"]["id"],
                            "error": {"code": -32603, "message": failure["code"]},
                        }
                    )
                    with contextlib.suppress(Exception):
                        await downstream_write.send(SessionMessage(reply))
        finally:
            # No automatic tool retry: a lost response may follow a completed side effect.
            for record, started in pending.values():
                try:
                    elapsed = int((time.monotonic() - started) * 1000)
                    info = dict(failure) if failure else diagnostic("SUBLLM-MCP-INTERRUPTED")
                    info["durationMs"] = elapsed
                    self.store.finish(
                        record,
                        None,
                        duration_ms=elapsed,
                        diagnostic=info,
                    )
                except Exception:
                    LOG.error("SUBLLM-ARCHIVE-WRITE: unfinished interaction remains pending")
