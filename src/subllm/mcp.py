"""Read-only MCP JSON-RPC adapter; all usage reads pass through DSL and PolicyBus."""

from __future__ import annotations

import json
import sys
from typing import Any

from .poa.bus import PolicyBus
from .poa.errors import PoaContractError
from .usage_dsl import ask, execute, grammar

VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}


def _tool(name: str, argument: str | None, description: str) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {argument: {"type": "string", "maxLength": 2048}} if argument else {},
            "required": [argument] if argument else [],
        },
        "annotations": {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    }


TOOLS = [
    _tool("execute_dsl", "command", "Read API history: usage.list provider=zai application=validator-agent limit=20"),
    _tool("nl_ask", "question", "Read API history in PL/EN: pokaż logi z.ai; show api usage. No paid calls."),
    _tool("describe_grammar", None, "Describe the closed read-only usage DSL and filters."),
]


def dispatch(message: Any, bus: PolicyBus) -> dict[str, Any] | None:
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request"}}
    request_id = message.get("id")
    if "id" not in message:
        return None
    if type(request_id) not in (str, int):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid request id"}}
    response = {"jsonrpc": "2.0", "id": request_id}
    method = message["method"]
    params = message.get("params", {})
    if not isinstance(params, dict):
        return {**response, "error": {"code": -32602, "message": "Expected object params"}}
    try:
        if method == "initialize":
            version = params.get("protocolVersion")
            result = {
                "protocolVersion": version if isinstance(version, str) and version in VERSIONS else "2025-06-18",
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "subllm-usage", "version": "1.13.0"},
                "instructions": "Read-only API usage. Empty history is not evidence of zero external traffic.",
            }
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": TOOLS}
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments", {})
            expected = {"execute_dsl": {"command"}, "nl_ask": {"question"}, "describe_grammar": set()}
            if (
                not isinstance(name, str)
                or name not in expected
                or not isinstance(args, dict)
                or set(args) != expected[name]
            ):
                raise PoaContractError("MCP-ARGS-001", "Unknown tool or invalid arguments")
            data = (
                execute(args["command"], bus)
                if name == "execute_dsl"
                else ask(args["question"], bus)
                if name == "nl_ask"
                else grammar()
            )
            result = {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
                "structuredContent": data,
                "isError": False,
            }
        elif method == "resources/list":
            result = {
                "resources": [
                    {"uri": "schema://current", "name": "SubLLM usage grammar", "mimeType": "application/json"}
                ]
            }
        elif method == "resources/read" and params.get("uri") == "schema://current":
            result = {
                "contents": [{"uri": "schema://current", "mimeType": "application/json", "text": json.dumps(grammar())}]
            }
        else:
            return {**response, "error": {"code": -32601, "message": "Method or resource not supported"}}
        return {**response, "result": result}
    except PoaContractError as exc:
        if method == "tools/call":
            return {
                **response,
                "result": {"isError": True, "content": [{"type": "text", "text": f"{exc.code}: {exc}"}]},
            }
        return {**response, "error": {"code": -32602, "message": str(exc)}}


def serve_stdio(bus: PolicyBus) -> None:
    while line := sys.stdin.readline(16385):
        if len(line) > 16384:
            return  # Oversized input is not an executable command.
        try:
            message = json.loads(line)
            response = dispatch(message, bus)
        except (ValueError, TypeError):
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
