"""Read the central routing contract from an operator-selected SubLLM Policy API (HEY-06).

Consumers (willman, heyasa) used to carry their own HTTP client for this query.
This is the one shared implementation: a bounded, read-only ``subllm.query/v1``
request, strict validation, digest verification and a short per-profile cache.
It never falls back: an unavailable endpoint raises
:class:`PolicyEndpointUnavailable` (a ``RuntimeError``), an invalid answer raises
:class:`InvalidRoutingContract` (a ``ValueError``).
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .poa.canonical import digest_document
from .poa.registry import EXPORT_CONTRACT_URI
from .routing_contract import SCHEMA as ROUTING_CONTRACT_SCHEMA

QUERY_SCHEMA = "subllm.query/v1"
MAX_CONTRACT_BYTES = 1_048_576
CONTRACT_FIELDS = frozenset({"schema", "version", "application", "function", "candidates", "execution", "sha256"})

_cache: dict[tuple[str, str, str], tuple[float, dict[str, Any]]] = {}
_lock = threading.Lock()
_key_locks: dict[tuple[str, str, str], threading.Lock] = {}


class PolicyEndpointUnavailable(RuntimeError):
    """The Policy API could not be reached or answered with an HTTP error."""


class InvalidRoutingContract(ValueError):
    """The Policy API answered with a document that is not a valid routing contract."""


def clear_routing_contract_cache() -> None:
    with _lock:
        _cache.clear()


def _query(endpoint: str, application: str, function: str, timeout: float) -> Any:
    parts = urlsplit(endpoint)
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise InvalidRoutingContract("SubLLM configuration endpoint must be an http(s) URL")
    payload = {"schema": QUERY_SCHEMA, "process_uri": EXPORT_CONTRACT_URI,
               "application": application, "function": function}
    request = Request(endpoint, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_CONTRACT_BYTES + 1)
    except HTTPError as exc:
        raise PolicyEndpointUnavailable(f"SubLLM configuration endpoint returned HTTP {exc.code}") from None
    except (URLError, TimeoutError, OSError) as exc:
        raise PolicyEndpointUnavailable("SubLLM configuration endpoint is unavailable") from exc
    if len(raw) > MAX_CONTRACT_BYTES:
        raise InvalidRoutingContract("SubLLM routing configuration exceeds 1 MiB")
    try:
        return json.loads(raw)
    except ValueError as exc:
        raise InvalidRoutingContract("SubLLM routing configuration is not JSON") from exc


def validate_routing_contract(contract: Any, application: str, function: str) -> dict[str, Any]:
    """Closed fields, supported version, matching profile, candidates and a correct digest."""
    if not isinstance(contract, dict) or set(contract) != CONTRACT_FIELDS:
        raise InvalidRoutingContract("Invalid SubLLM routing configuration fields")
    if (contract["schema"] != ROUTING_CONTRACT_SCHEMA or type(contract["version"]) is not int
            or contract["version"] != 1):
        raise InvalidRoutingContract("Unsupported SubLLM routing configuration version")
    if (contract["application"], contract["function"]) != (application, function):
        raise InvalidRoutingContract("SubLLM routing configuration profile mismatch")
    if not isinstance(contract["candidates"], list) or not contract["candidates"]:
        raise InvalidRoutingContract("SubLLM routing configuration has no candidates")
    body = {key: value for key, value in contract.items() if key != "sha256"}
    if digest_document(body) != contract["sha256"]:
        raise InvalidRoutingContract("SubLLM routing configuration checksum mismatch")
    return contract


def fetch_routing_contract(endpoint: str, application: str, function: str, *, timeout: float = 5.0,
                           cache_seconds: float = 60.0) -> dict[str, Any]:
    """The verified central routing contract for ``application/function`` (single-flight per profile)."""
    key = (endpoint, application, function)
    with _lock:
        gate = _key_locks.setdefault(key, threading.Lock())
    with gate:
        with _lock:
            cached = _cache.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        contract = validate_routing_contract(_query(endpoint, application, function, timeout), application, function)
        with _lock:
            _cache[key] = (time.monotonic() + cache_seconds, contract)
        return contract
