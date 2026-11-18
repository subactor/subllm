"""Browser origin and bearer-token checks for the local proxy (SUB-01, extracted in SUB-08).

Only loopback pages and explicitly listed origins may read responses; routed (possibly paid/cloud)
completions can additionally require a bearer token.
"""

from __future__ import annotations

import hmac
import os
from typing import Any
from urllib.parse import urlsplit

from .errors import SubLLMError

PROXY_ALLOWED_ORIGINS_ENV = "SUBLLM_PROXY_ALLOWED_ORIGINS"
PROXY_BEARER_ENV = "SUBLLM_PROXY_TOKEN"
_LOOPBACK_ORIGIN_HOSTS = {"127.0.0.1", "localhost", "::1"}


class ProxyUnauthorizedError(SubLLMError):
    """A routed completion was requested without the configured proxy bearer token."""


def require_route_bearer(headers: Any) -> None:
    """Raise ProxyUnauthorizedError when SUBLLM_PROXY_TOKEN is set and the request lacks it."""
    expected = os.environ.get(PROXY_BEARER_ENV, "")
    if not expected:
        return
    supplied = (headers.get("Authorization") or "") if headers is not None else ""
    if not hmac.compare_digest(supplied.encode("utf-8"), f"Bearer {expected}".encode()):
        raise ProxyUnauthorizedError("a valid proxy bearer token is required for routed models")


def _normalized_origin(origin: str) -> str:
    return origin.strip().rstrip("/").lower()


def proxy_origin_allowed(origin: str) -> bool:
    """Loopback browser origins and those listed in SUBLLM_PROXY_ALLOWED_ORIGINS (comma separated)."""
    try:
        parts = urlsplit(origin.strip())
        host = parts.hostname
    except ValueError:
        return False
    if parts.scheme in {"http", "https"} and host in _LOOPBACK_ORIGIN_HOSTS:
        return True
    listed = {_normalized_origin(item) for item in os.environ.get(PROXY_ALLOWED_ORIGINS_ENV, "").split(",")}
    return bool(origin.strip()) and _normalized_origin(origin) in listed - {""}
