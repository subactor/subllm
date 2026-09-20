"""Gemini API (Google AI Studio key) through the native generateContent REST endpoint."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

from .cli_common import JSON_OBJECT_INSTRUCTION, response_mode
from .errors import CompletionError
from .native_http import NativeHTTPError, plain_messages, post_json

_ROLES = {"user": "user", "assistant": "model"}
# 503 UNAVAILABLE means this model is overloaded right now; another Gemini model is usually fine.
_MODEL_SCOPED_STATUSES = frozenset({503})


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
    mode, schema = response_mode(response_format, name="Gemini")
    system: list[str] = []
    contents: list[dict[str, Any]] = []
    for role, text in plain_messages(messages):
        if role == "system":
            system.append(text)
        elif role in _ROLES:
            contents.append({"role": _ROLES[role], "parts": [{"text": text}]})
        else:
            raise CompletionError(f"Gemini does not accept role {role!r}", diagnostic_code="SUBLLM-GEMINI-ROLE")
    if not contents:
        raise CompletionError("Gemini requires at least one user message", diagnostic_code="SUBLLM-GEMINI-ROLE")
    generation: dict[str, Any] = {}
    parameters = dict(model_parameters or {})
    for source, target in (("temperature", "temperature"), ("top_p", "topP"), ("max_tokens", "maxOutputTokens")):
        if source in parameters:
            generation[target] = parameters[source]
    if mode == "json_object":
        generation["responseMimeType"] = "application/json"
        system.append(JSON_OBJECT_INSTRUCTION)
    elif mode == "json_schema":
        generation["responseMimeType"] = "application/json"
        generation["responseJsonSchema"] = schema
    body: dict[str, Any] = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system)}]}
    if generation:
        body["generationConfig"] = generation
    raw = post_json(
        f"{api_base.rstrip('/')}/models/{quote(model, safe='')}:generateContent",
        body, {"x-goog-api-key": api_key}, timeout_seconds,
        model_scoped_statuses=_MODEL_SCOPED_STATUSES,
    )
    try:
        candidate = raw["candidates"][0]
        text = "".join(str(part.get("text", "")) for part in candidate["content"]["parts"]).strip()
    except (KeyError, IndexError, TypeError, AttributeError):
        raise NativeHTTPError("invalid_response") from None
    if not text:
        raise NativeHTTPError("invalid_response")
    meta = raw.get("usageMetadata") if isinstance(raw, Mapping) else None
    usage: dict[str, int] = {}
    if isinstance(meta, Mapping):
        for source, target in (("promptTokenCount", "input_tokens"), ("candidatesTokenCount", "output_tokens"),
                               ("cachedContentTokenCount", "cached_input_tokens")):
            value = meta.get(source)
            if type(value) is int and value >= 0:
                usage[target] = value
    return text, usage, str(candidate.get("finishReason", "STOP")).lower()
