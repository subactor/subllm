"""Bounded JSON-over-HTTPS client for provider-native APIs (Gemini, Anthropic).

Only the fixed provider base from policy is contacted, redirects are refused, the
credential travels in a header (never in a URL or an error message) and both the
response size and the time are bounded.
"""
from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from collections.abc import Mapping
from http.client import HTTPException
from threading import TIMEOUT_MAX
from typing import Any

from .errors import CompletionError

HTTP_SAFETY_PROFILE = "bounded-no-proxy-no-redirect-v1"
MAX_RESPONSE_BYTES = 4_000_000
MAX_ERROR_RESPONSE_BYTES = 16_384
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_JSON_DEPTH = 64


def decode_response_json(payload: bytes) -> Any:
    """Decode a bounded body and reject excessive nesting without recursive walking."""
    result = json.loads(payload.decode("utf-8"))
    stack = [iter((result,))]
    while stack:
        try:
            item = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        if isinstance(item, (dict, list)):
            if len(stack) > MAX_JSON_DEPTH:
                raise ValueError("Provider JSON exceeds nesting limit")
            stack.append(iter(item.values() if isinstance(item, dict) else item))
    return result


def _anthropic_credit_refusal(error: urllib.error.HTTPError, provider: str | None) -> bool:
    if provider != "claude" or error.code != 400:
        return False
    try:
        payload = error.read(MAX_ERROR_RESPONSE_BYTES + 1)
        if len(payload) > MAX_ERROR_RESPONSE_BYTES:
            return False
        raw = decode_response_json(payload)
    except (ValueError, OSError, AttributeError, TypeError, RecursionError):
        return False
    detail = raw.get("error") if isinstance(raw, Mapping) else None
    if not isinstance(detail, Mapping) or detail.get("type") != "invalid_request_error":
        return False
    message = detail.get("message")
    return isinstance(message, str) and message.startswith(
        "Your credit balance is too low to access the Anthropic API."
    )


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
        if self.outcome == "quota_exhausted":
            return True  # Continue to another permitted provider, never retry this account.
        status = self.status
        if status is None:
            return True
        if status == 404:
            return True
        return status in {401, 402, 403, 408, 409, 425, 429} or status >= 500


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:  # noqa: D102
        return None


def normalize_timeout(timeout: float) -> float:
    """Reject invalid numbers and values the platform cannot represent as a wait."""
    try:
        valid = (not isinstance(timeout, bool) and isinstance(timeout, (int, float))
                 and math.isfinite(timeout) and 0 < timeout <= TIMEOUT_MAX)
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError("HTTP timeout must be finite and positive")
    return float(timeout)


def open_request(request: urllib.request.Request, *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> Any:
    """One request, with no ambient proxy, redirect or unbounded socket timeout."""
    timeout = normalize_timeout(timeout)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)
    return opener.open(request, timeout=timeout)  # noqa: S310 - caller validates policy-owned URL


def post_json(
    url: str,
    body: Mapping[str, Any],
    headers: Mapping[str, str],
    timeout_seconds: float,
    *,
    model_scoped_statuses: frozenset[int] = frozenset(),
    quota_provider: str | None = None,
) -> Any:
    if not url.startswith("https://"):
        raise NativeHTTPError("transport_error")
    try:
        timeout_seconds = normalize_timeout(timeout_seconds)
    except ValueError:
        raise NativeHTTPError("transport_error") from None
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", **dict(headers)},
        method="POST",
    )
    try:
        with open_request(request, timeout=timeout_seconds) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        try:
            exhausted = _anthropic_credit_refusal(exc, quota_provider)
        finally:
            exc.close()
        if exhausted:
            raise NativeHTTPError("quota_exhausted", status=status) from None
        raise NativeHTTPError(
            "model_unavailable" if status == 404 else f"http_{status}",
            status=status, model_scoped=status in model_scoped_statuses,
        ) from None
    except TimeoutError:
        raise NativeHTTPError("timeout") from None
    except HTTPException:
        raise NativeHTTPError("invalid_response") from None
    except TypeError:
        raise NativeHTTPError("transport_error") from None
    except (urllib.error.URLError, OSError):
        raise NativeHTTPError("transport_error") from None
    if len(payload) > MAX_RESPONSE_BYTES:
        raise NativeHTTPError("invalid_response")
    try:
        return decode_response_json(payload)
    except (ValueError, RecursionError):
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
