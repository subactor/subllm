"""Raw Ollama forward helpers for the local proxy: request timeout and usage counts (SUB-04/05/08).

Pure functions without I/O; the proxy handler owns the actual HTTP forward.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from typing import Any

UPSTREAM_FORWARD_TIMEOUT_DEFAULT = 120.0
UPSTREAM_FORWARD_TIMEOUT_BOUNDS = (1.0, 900.0)
FORWARD_USAGE_PATHS = frozenset({"/api/chat", "/api/generate", "/api/embed", "/v1/chat/completions",
                                 "/v1/completions", "/v1/embeddings"})
_TRAILING_DOCUMENT_LIMIT = 4


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
