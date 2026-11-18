"""Raw Ollama forward helpers for the local proxy: request timeout and usage counts (SUB-04/05/08).

Pure functions without I/O; the proxy handler owns the actual HTTP forward.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from typing import Any

UPSTREAM_FORWARD_TIMEOUT_DEFAULT = 120.0
UPSTREAM_FORWARD_TIMEOUT_BOUNDS = (1.0, 900.0)
FORWARD_USAGE_PATHS = frozenset({"/api/chat", "/api/generate", "/api/embed", "/v1/chat/completions",
                                 "/v1/completions", "/v1/embeddings"})
_TRAILING_DOCUMENT_LIMIT = 4
_CLIENT_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_.:/-]{1,128}$")
MAX_FORWARD_JSON_BYTES = 1_048_576


class ForwardJSONError(ValueError):
    """Typed HTTP 400 error for invalid forward/inference JSON payloads without leaking input."""

    def __init__(self, code: str, message: str, *, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ForwardJSONError("INVALID_JSON_OBJECT", f"duplicate JSON property: {key}")
        result[key] = value
    return result


def parse_strict_json_object(raw: bytes | str, *, max_bytes: int = MAX_FORWARD_JSON_BYTES) -> dict[str, Any]:
    """Validate byte size, UTF-8, duplicate keys, finiteness and top-level dict without leaking input."""
    if isinstance(raw, str):
        raw_bytes = raw.encode("utf-8", errors="surrogatepass")
    elif isinstance(raw, (bytes, bytearray)):
        raw_bytes = bytes(raw)
    else:
        raise ForwardJSONError("INVALID_JSON_OBJECT", "request body must be bytes or text")
    if len(raw_bytes) > max_bytes:
        raise ForwardJSONError("REQUEST_TOO_LARGE", "request body exceeds maximum byte budget", status=413)
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ForwardJSONError("INVALID_JSON_OBJECT", "request body must be valid UTF-8") from exc
    if not text.strip():
        raise ForwardJSONError("INVALID_JSON_OBJECT", "request body must contain a JSON object")
    try:
        parsed = json.loads(
            text,
            object_pairs_hook=_unique_json_pairs,
            parse_constant=lambda c: (_ for _ in ()).throw(
                ForwardJSONError("INVALID_JSON_OBJECT", f"nonfinite JSON constant is forbidden: {c}")
            ),
        )
    except ForwardJSONError:
        raise
    except (ValueError, TypeError, RecursionError) as exc:
        raise ForwardJSONError("INVALID_JSON_OBJECT", "request body is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ForwardJSONError("INVALID_JSON_OBJECT", "JSON request root must be an object")
    return parsed


def correlate_forward_telemetry(
    path: str,
    body: bytes,
    *,
    client_request_id: str | None,
    proxy_request_id: str,
    attempt_id: str,
    auth_owner: str | None = None,
    application: str | None = None,
    function: str | None = None,
    seen_attempts: set[str] | None = None,
) -> dict[str, Any] | None:
    """Build correlated, content-free forward telemetry with attempt_id dedup and unknown-vs-zero usage."""
    if client_request_id is not None and (
        not isinstance(client_request_id, str) or _CLIENT_REQUEST_ID_RE.fullmatch(client_request_id) is None
    ):
        raise ForwardJSONError("INVALID_REQUEST", "invalid client_request_id header")
    if seen_attempts is not None:
        if attempt_id in seen_attempts:
            return None
        seen_attempts.add(attempt_id)
    counts = forward_usage_counts(path, body)
    prompt_tokens = counts.get("prompt_tokens")
    completion_tokens = counts.get("completion_tokens")
    return {
        "client_request_id": client_request_id,
        "proxy_request_id": proxy_request_id,
        "attempt_id": attempt_id,
        "path": path,
        "auth_owner": auth_owner,
        "application": application,
        "function": function,
        "usage_known": bool(counts),
        "input_tokens": prompt_tokens,
        "output_tokens": completion_tokens,
    }


def upstream_forward_timeout(payload: Any) -> float:
    """Raw Ollama forward timeout from the request ``timeout`` field, clamped to 1-900 s (SUB-05)."""
    value = payload.get("timeout") if isinstance(payload, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return UPSTREAM_FORWARD_TIMEOUT_DEFAULT
    low, high = UPSTREAM_FORWARD_TIMEOUT_BOUNDS
    return float(min(max(value, low), high))


def forward_usage_counts(path: str, body: bytes) -> dict[str, int]:
    """Token counts from a raw Ollama forward response; never returns or keeps content (SUB-04).

    Ollama native responses carry ``prompt_eval_count``/``eval_count`` in the JSON body or in the
    final ``done`` line of an NDJSON stream; OpenAI-compatible ones carry ``usage`` in the JSON body
    or in an SSE ``data:`` chunk.
    """
    try:
        text = body.decode("utf-8")
    except (UnicodeDecodeError, AttributeError):
        return {}
    for document in _trailing_json_documents(text):
        counts = _usage_from_document(path, document)
        if counts is not None:
            return counts
    return {}


def _trailing_json_documents(text: str) -> list[Any]:
    """The last few JSON documents of a body, NDJSON stream or SSE stream, newest first."""
    documents: list[Any] = []
    for line in reversed(text.splitlines() or [text]):
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            continue
        try:
            documents.append(json.loads(line))
        except ValueError:
            continue
        if len(documents) >= _TRAILING_DOCUMENT_LIMIT:
            break
    return documents


def _usage_from_document(path: str, document: Any) -> dict[str, int] | None:
    if not isinstance(document, dict):
        return None
    if path.startswith("/api/") and ("prompt_eval_count" in document or "eval_count" in document):
        return _non_negative_counts((("prompt_tokens", document.get("prompt_eval_count")),
                                     ("completion_tokens", document.get("eval_count"))))
    usage = document.get("usage")
    if isinstance(usage, dict):
        return _non_negative_counts((key, usage.get(key)) for key in ("prompt_tokens", "completion_tokens"))
    return None


def _non_negative_counts(pairs: Iterable[tuple[str, Any]]) -> dict[str, int]:
    return {key: value for key, value in pairs if type(value) is int and value >= 0}
