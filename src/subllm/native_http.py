"""Bounded JSON-over-HTTPS client for provider-native APIs (Gemini, Anthropic).

Only the fixed provider base from policy is contacted, redirects are refused, the
credential travels in a header (never in a URL or an error message) and both the
response size and the time are bounded.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any

from .errors import CompletionError

MAX_RESPONSE_BYTES = 4_000_000


class NativeHTTPError(Exception):
    """A provider call failed; `outcome` uses the same vocabulary as the OpenAI worker."""

    def __init__(self, outcome: str, *, status: int | None = None, model_scoped: bool = False) -> None:
        super().__init__(outcome)
        self.outcome = outcome
        self.status = status
        # A status the provider reports per model (e.g. Gemini 503 "model overloaded"): other models may still serve.
        self.model_scoped = model_scoped

    @property
    def provider_level(self) -> bool:
        return not self.model_scoped and self.outcome not in {"model_unavailable", "invalid_response"}

    @property
    def retryable(self) -> bool:
        status = self.status
        if status is None:
            return True
        if status == 404:
            return True
        return status in {401, 402, 403, 408, 409, 425, 429} or status >= 500


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:  # noqa: D102
        return None


def post_json(
    url: str,
    body: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout_seconds: float,
    *,
    model_scoped_statuses: frozenset[int] = frozenset(),
) -> Any:
    if not url.startswith("https://"):
        raise NativeHTTPError("transport_error")
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", **dict(headers)},
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed https base
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        raise NativeHTTPError(
            "model_unavailable" if status == 404 else f"http_{status}",
            status=status, model_scoped=status in model_scoped_statuses,
        ) from None
    except TimeoutError:
        raise NativeHTTPError("timeout") from None
    except (urllib.error.URLError, OSError):
        raise NativeHTTPError("transport_error") from None
    if len(payload) > MAX_RESPONSE_BYTES:
        raise NativeHTTPError("invalid_response")
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NativeHTTPError("invalid_response") from None


def plain_messages(messages: Any) -> list[tuple[str, str]]:
    """Return (role, text) pairs; anything that is not plain text fails closed."""
    result: list[tuple[str, str]] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        if isinstance(content, list):
            parts = []
            for part in content:
                if not isinstance(part, Mapping) or part.get("type") != "text":
                    raise CompletionError("this transport accepts text messages only",
                                          diagnostic_code="SUBLLM-NATIVE-UNSUPPORTED-CONTENT")
                parts.append(str(part.get("text", "")))
            content = "\n".join(parts)
        elif not isinstance(content, str):
            raise CompletionError("this transport accepts text messages only",
                                  diagnostic_code="SUBLLM-NATIVE-UNSUPPORTED-CONTENT")
        result.append((role, content))
    return result
