from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from .errors import CompletionError

MAX_CURSOR_WORKER_REQUEST_BYTES = 4_000_000


def _request(source: Any) -> Mapping[str, Any]:
    if not isinstance(source, Mapping) or set(source) != {
        "schema", "model", "api_key", "cwd", "name", "prompt",
    }:
        raise CompletionError("Cursor worker request must be a closed JSON object")
    if source.get("schema") != "subllm.cursor-worker-request/v1":
        raise CompletionError("Cursor worker request schema is not supported")
    for field in ("model", "api_key", "cwd", "name", "prompt"):
        value = source.get(field)
        if not isinstance(value, str) or not value or "\x00" in value:
            raise CompletionError(f"Cursor worker {field} must be a non-empty safe string")
    return source


def _usage(result: Any) -> Mapping[str, Any]:
    usage = getattr(result, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, Mapping):
        return dict(usage)
    try:
        return asdict(usage)
    except TypeError:
        return {}


def _execute(request: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError as exc:
        raise CompletionError(
            "provider cursor requires the optional dependency 'subactor-subllm[cursor]'"
        ) from exc

    option_values = {
        "model": request["model"],
        "api_key": request["api_key"],
        "local": LocalAgentOptions(cwd=request["cwd"], setting_sources=[]),
        "tools": [],
        "name": request["name"],
    }
    options = AgentOptions(**option_values)
    try:
        with Agent.create(options) as agent:
            result = agent.send(request["prompt"]).wait()
    except Exception as exc:  # noqa: BLE001 - never project SDK details or credentials
        raise CompletionError("Cursor SDK request failed") from exc
    status = str(getattr(getattr(result, "status", ""), "value", getattr(result, "status", ""))).lower()
    content = str(getattr(result, "result", "") or "")
    if status != "finished" or not content:
        raise CompletionError(f"Cursor SDK ended with status {status or 'unknown'}")
    return {
        "schema": "subllm.cursor-worker-result/v1",
        "status": "SUCCESS",
        "content": content,
        "usage": dict(_usage(result)),
        "finish_reason": "",
        "run_id": str(getattr(result, "id", "") or ""),
    }


def main() -> int:
    try:
        encoded = sys.stdin.buffer.read(MAX_CURSOR_WORKER_REQUEST_BYTES + 1)
        if len(encoded) > MAX_CURSOR_WORKER_REQUEST_BYTES:
            raise CompletionError("Cursor worker request exceeds 4000000 bytes")
        request = _request(json.loads(encoded.decode("utf-8")))
        result = _execute(request)
    except (UnicodeError, json.JSONDecodeError, CompletionError) as exc:
        print(f"subllm-cursor-worker: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
