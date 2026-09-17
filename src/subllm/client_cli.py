from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from typing import Any

from .client_routes import complete
from .errors import CompletionError

MAX_COMPLETION_REQUEST_BYTES = 1_000_000


def _completion_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not 0 < timeout <= 900:
        raise argparse.ArgumentTypeError("timeout must be greater than 0 and at most 900 seconds")
    return timeout


def _completion_request(source: Any) -> tuple[list[Mapping[str, Any]], str | None, Mapping[str, Any] | None]:
    if not isinstance(source, Mapping) or set(source) - {
        "schema", "messages", "request_id", "response_format",
    }:
        raise CompletionError("completion request must be a closed JSON object")
    if source.get("schema") != "subllm.completion-request/v1":
        raise CompletionError("completion request schema is not supported")
    messages = source.get("messages")
    if (
        not isinstance(messages, list)
        or not 1 <= len(messages) <= 128
        or any(not isinstance(message, Mapping) for message in messages)
    ):
        raise CompletionError("completion request messages must contain 1 to 128 objects")
    request_id = source.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str)
        or not 6 <= len(request_id) <= 64
        or any(character in request_id for character in "\r\n\x00")
    ):
        raise CompletionError("completion request_id must contain 6 to 64 safe characters")
    response_format = source.get("response_format")
    if response_format is not None and not isinstance(response_format, Mapping):
        raise CompletionError("completion response_format must be an object")
    return messages, request_id, response_format


def completion_main(argv: Sequence[str] | None = None) -> int:
    """Closed stdin-JSON adapter for policy-owned completion and failover."""
    parser = argparse.ArgumentParser(prog="subllm-complete")
    parser.add_argument("application")
    parser.add_argument("function")
    parser.add_argument("--timeout", type=_completion_timeout, default=30.0)
    args = parser.parse_args(argv)
    try:
        encoded = sys.stdin.buffer.read(MAX_COMPLETION_REQUEST_BYTES + 1)
        if len(encoded) > MAX_COMPLETION_REQUEST_BYTES:
            raise CompletionError("completion request exceeds 1000000 bytes")
        request = json.loads(encoded.decode("utf-8"))
        messages, request_id, response_format = _completion_request(request)
        result = complete(
            args.application,
            args.function,
            messages,
            timeout_seconds=args.timeout,
            request_id=request_id,
            response_format=response_format,
        )
    except (UnicodeError, json.JSONDecodeError, CompletionError) as exc:
        print(f"subllm-complete: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "schema": "subllm.completion-result/v1",
        "status": "SUCCESS",
        "content": result.content,
        "provider": result.provider,
        "model": result.model,
        "usage": dict(result.usage),
        "finish_reason": result.finish_reason,
        "attempts": [asdict(attempt) for attempt in result.attempts],
    }, ensure_ascii=False, sort_keys=True))
    return 0
