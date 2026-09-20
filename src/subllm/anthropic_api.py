"""Anthropic Messages API (ANTHROPIC_API_KEY) through the native REST endpoint."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .cli_common import JSON_OBJECT_INSTRUCTION, response_mode
from .errors import CompletionError
from .native_http import NativeHTTPError, plain_messages, post_json

ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_TOKENS = 4096


def invoke(
    api_base: str,
    api_key: str,
    model: str,
    messages: Sequence[Mapping[str, Any]],
    timeout_seconds: float,
    response_format: Mapping[str, Any] | None,
    model_parameters: Mapping[str, Any] | None = None,
) -> tuple[str, dict[str, int], str]:
    """Return (content, usage, finish_reason). Raises NativeHTTPError on transport problems."""
    mode, schema = response_mode(response_format, name="Anthropic")
    system: list[str] = []
    turns: list[dict[str, str]] = []
    for role, text in plain_messages(messages):
        if role == "system":
            system.append(text)
        elif role in {"user", "assistant"}:
            turns.append({"role": role, "content": text})
        else:
            raise CompletionError(f"Anthropic does not accept role {role!r}", diagnostic_code="SUBLLM-ANTHROPIC-ROLE")
    if not turns:
        raise CompletionError("Anthropic requires at least one user message", diagnostic_code="SUBLLM-ANTHROPIC-ROLE")
    parameters = dict(model_parameters or {})
    if mode == "json_object":
        system.append(JSON_OBJECT_INSTRUCTION)
    elif mode == "json_schema":
        system.append(f"{JSON_OBJECT_INSTRUCTION} It must satisfy this JSON Schema: {schema}")
    body: dict[str, Any] = {"model": model, "messages": turns,
                            "max_tokens": int(parameters.get("max_tokens", DEFAULT_MAX_TOKENS))}
    if system:
        body["system"] = "\n\n".join(system)
    for name in ("temperature", "top_p"):
        if name in parameters:
            body[name] = parameters[name]
    raw = post_json(f"{api_base.rstrip('/')}/messages", body,
                    {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}, timeout_seconds)
    try:
        text = "".join(str(block.get("text", "")) for block in raw["content"] if block.get("type") == "text").strip()
    except (KeyError, TypeError, AttributeError):
        raise NativeHTTPError("invalid_response") from None
    if not text:
        raise NativeHTTPError("invalid_response")
    meta = raw.get("usage") if isinstance(raw, Mapping) else None
    usage: dict[str, int] = {}
    if isinstance(meta, Mapping):
        for source, target in (("input_tokens", "input_tokens"), ("output_tokens", "output_tokens"),
                               ("cache_read_input_tokens", "cached_input_tokens")):
            value = meta.get(source)
            if type(value) is int and value >= 0:
                usage[target] = value
    return text, usage, str(raw.get("stop_reason") or "stop")
