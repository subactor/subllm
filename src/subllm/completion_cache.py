"""Opt-in exact text completion reuse, composed with procache and native audit.

The private cache stores response text, just like the native archive. Choose a
private path, an explicit account scope and a short TTL for mutable model aliases.
Only complete API text answers with a committed source archive are reusable.
Each replay runs the current acceptance checks and writes a completion_replay
archive; it never writes an inference usage row or consumes generation allowance.
Native procache flights last 120 seconds: requests longer than 60 seconds bypass
reuse. Waiting callers have their own timeout; a killed process's flight expires
through procache rather than authorizing an overlapping inference.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import time
from contextlib import contextmanager, suppress
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from pathlib import Path

from .audit import ArchiveReference, audit_attempt
from .client_types import CompletionCacheReceipt, CompletionResponse, _RetryableAttemptError
from .errors import CompletionError
from .interaction_context import ACTIVE_ARCHIVE, begin_attempt, finish_attempt
from .quality import validate_response
from .quality_schema import declared_schema_gate, schema_gate

_API = {"openai-compatible", "anthropic", "gemini-sdk"}
_PARAMETERS = {"temperature", "top_p", "top_k", "seed", "max_tokens", "max_completion_tokens",
               "frequency_penalty", "presence_penalty", "reasoning_effort"}
_COMPLETE = {"stop", "end_turn", "stop_sequence", "STOP"}
_TOKENS = {"prompt_tokens", "completion_tokens", "total_tokens", "input_tokens", "output_tokens",
           "reasoning_tokens", "generation_output_tokens", "visible_output_tokens"}


@dataclass(frozen=True)
class CompletionCache:
    """Operator-selected private cache; all identity strings are required.

    Example: CompletionCache(path, ttl=30, scope="tenant-a", model_revision="v1",
    criterion_version="forge-tests-v3"). Increment criterion_version when task
    acceptance changes, model_revision when a model alias changes, or use
    complete(..., force_generation=True) to explore a fresh answer. TTL is a
    maximum age at read time, including when shortened after a restart.
    """

    path: str | Path
    ttl: float
    scope: str
    model_revision: str
    criterion_version: str

    def __post_init__(self):
        if type(self.ttl) not in {int, float} or not math.isfinite(self.ttl) or self.ttl <= 0:
            raise CompletionError("completion cache TTL must be finite and positive")
        for name in ("scope", "model_revision", "criterion_version"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip() or len(value) > 256:
                raise CompletionError(f"completion cache {name} must be a nonempty bounded string")
        object.__setattr__(self, "path", Path(self.path))


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_json(value)).hexdigest()


def _content_digest(content):
    return hashlib.sha256(content.encode()).hexdigest()


def _text_only(messages):
    return bool(messages) and all(
        isinstance(message, dict) and set(message) == {"role", "content"}
        and message["role"] in {"system", "user", "assistant"} and isinstance(message["content"], str)
        for message in messages
    )


def _has_tools(value):
    if isinstance(value, dict):
        return any((key in {"tools", "tool_calls", "function_call", "tool_use"} and bool(item))
                   or _has_tools(item) for key, item in value.items())
    return isinstance(value, list) and any(_has_tools(item) for item in value)


def _store():
    from .interaction_store import get_default_interaction_store

    return get_default_interaction_store()


def _receipt(state, key="", payload=None):
    if payload is None:
        return CompletionCacheReceipt(state, key)
    usage = tuple(sorted((key, value) for key, value in payload["usage"].items()
                         if key in _TOKENS and (value is None or type(value) is int and value >= 0)))
    return CompletionCacheReceipt(state, key, payload["request_id"],
                                  ArchiveReference(**payload["archive"]), payload["digest"], usage)


def _encode(response, key):
    if response.finish_reason not in _COMPLETE or _has_tools(dict(response.raw)):
        return b""
    source = next((attempt for attempt in reversed(response.audit.attempts)
                   if attempt.status == "success" and attempt.provider == response.provider
                   and attempt.model == response.model and attempt.archive_state == "stored"
                   and attempt.archive is not None), None)
    if source is None:
        return b""
    return _json({"version": 1, "key": key, "request_id": response.audit.request_id,
                  "archive": asdict(source.archive), "content": response.content,
                  "digest": _content_digest(response.content), "provider": response.provider,
                  "model": response.model, "usage": dict(response.usage),
                  "finish_reason": response.finish_reason, "created_at": time.time()})


def _decode(value, key, config, routes, messages, response_format):
    """Corrupt, expired, deleted or wrong-profile sources are cache misses."""
    if len(value) > 4 * 1024 * 1024:
        return None
    try:
        payload = json.loads(value)
        reference = ArchiveReference(**payload["archive"])
        if (payload["version"] != 1 or payload["key"] != key
                or type(payload["created_at"]) not in {int, float}
                or not 0 <= time.time() - payload["created_at"] < config.ttl
                or not isinstance(payload["content"], str)
                or payload["digest"] != _content_digest(payload["content"])
                or payload["finish_reason"] not in _COMPLETE):
            return None
        route = next((route for route in routes if route.provider == payload["provider"]
                      and route.wire_model == payload["model"]), None)
        if route is None:
            return None
        store = _store()
        saved = store.get_interaction(reference.id, reference.day) if store is not None else None
        if (not saved or saved["status"] != "success" or saved["finished_at"] is None
                or saved["kind"] != "llm_attempt"
                or saved["correlation_id"] != payload["request_id"]
                or saved["correlation_id"] != reference.correlation_id
                or saved["caller"] != route.application
                or saved["metadata"]["function"] != route.function
                or saved["metadata"]["provider"] != route.provider
                or saved["metadata"]["model"] != route.wire_model
                or saved["request"]["messages"] != list(messages)
                or saved["request"]["response_format"] != response_format
                or saved["response"]["content"] != payload["content"]
                or saved["response"]["finish_reason"] != payload["finish_reason"]
                or saved["response"]["usage"] != payload["usage"]):
            return None
        return payload
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return None


def _open_cache(config, deadline, check):
    from procache import SQLiteResponseCache

    # Create sensitive content storage with private mode before SQLite opens it.
    config.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        descriptor = os.open(config.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        pass
    else:
        os.close(descriptor)
    mode = config.path.stat().st_mode
    if config.path.is_symlink() or not stat.S_ISREG(mode) or stat.S_IMODE(mode) & 0o077:
        raise OSError("completion cache requires a private regular file")

    class CheckedCache(SQLiteResponseCache):
        def get(self, key, *, now=None):
            entry = super().get(key, now=now)
            return entry if entry is None or check(entry.value) else None

        @contextmanager
        def _lock_for(self, key):
            lock = SQLiteResponseCache._lock_for(key)
            if not lock.acquire(timeout=max(0, deadline - time.monotonic())):
                raise CompletionError("completion cache wait timed out", diagnostic_code="SUBLLM-CACHE-TIMEOUT")
            try:
                yield
            finally:
                lock.release()

        def _flight_active(self, key):
            if time.monotonic() >= deadline:
                raise CompletionError("completion cache wait timed out", diagnostic_code="SUBLLM-CACHE-TIMEOUT")
            return super()._flight_active(key)

    return CheckedCache(config.path, namespace="subllm-completion-v1")


def _candidate(payload, key):
    receipt = _receipt("hit", key, payload)
    attribution = {"source_request_id": receipt.source_request_id,
                   "source_archive": asdict(receipt.source_archive),
                   "content_digest": receipt.content_digest, "source_usage": dict(receipt.source_usage)}
    return CompletionResponse(payload["content"], payload["provider"], payload["model"],
                              {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                               "input_tokens": 0, "output_tokens": 0}, payload["finish_reason"],
                              raw={"cache": attribution}, cache=receipt)


def _replay(payload, key, routes, messages, response_format, capture, generation):
    if payload["request_id"] == capture.request_id:
        raise CompletionError("request_id must identify a new cache operation")
    response = _candidate(payload, key)
    route = next(route for route in routes
                 if route.provider == response.provider and route.wire_model == response.model)
    with audit_attempt(capture.request_id, route) as observation:
        observation.status, observation.journal_state = "cache_hit", "disabled"
        archive = begin_attempt(route, messages, response_format, request_id=capture.request_id,
                                native_request={"messages": list(messages), "response_format": response_format,
                                                "cache": response.raw["cache"]}, kind="completion_replay")
        finish_attempt(archive, route, response, None, 0)
    return replace(response, audit=capture.receipt(), generation=generation.receipt())


def cached_complete(config, invoke, *, application, function, messages, response_format, environ, credentials,
                    model, quality_gate, quality_schema, runtime_policy, generation, capture,
                    timeout_seconds, force_generation):
    if not isinstance(config, CompletionCache) or type(force_generation) is not bool:
        raise CompletionError("cache must be CompletionCache and force_generation must be boolean")
    from . import adaptive, client_routes

    adaptive_policy = adaptive.policy(environ)
    if (force_generation or not _text_only(messages) or ACTIVE_ARCHIVE.get() is not None
            or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 60
            or adaptive_policy and adaptive_policy.get("routes", {}).get(f"{application}/{function}")):
        return replace(invoke(), cache=_receipt("bypass"))
    if model is not None and (not isinstance(model, str) or not model.strip() or len(model) > 200):
        raise CompletionError("model must be a nonempty string of at most 200 characters")
    gate = declared_schema_gate(response_format, schema_gate(quality_schema, quality_gate))
    if quality_gate is not None and not callable(quality_gate):
        raise CompletionError("quality_gate must be callable")
    routes = client_routes._requested_model_routes(
        client_routes.available_routes(application, function, environ=environ, credentials=credentials),
        None if model == f"{application}/{function}" else model,
    )
    if not routes or any(route.transport not in _API or route.modality != "text"
                         or set(route.model_parameters) - _PARAMETERS for route in routes):
        return replace(invoke(), cache=_receipt("bypass"))
    routes = [replace(route, model_parameters=deepcopy(dict(route.model_parameters)),
                      extra_headers=deepcopy(dict(route.extra_headers))) for route in routes]
    # Hash credentials and headers only in memory. Neither raw keys nor prompts
    # are persisted in the lookup key; the source archive owns prompt custody.
    key = _digest({"version": 1, "application": application, "function": function,
                   "messages": list(messages), "response_format": response_format,
                   "quality_schema": quality_schema, "scope": config.scope,
                   "model_revision": config.model_revision, "criterion": config.criterion_version,
                   "routes": [asdict(route) for route in routes],
                   "policy": hashlib.sha256(runtime_policy.source.read_bytes()).hexdigest(),
                   "execution": asdict(runtime_policy.execution), "limits": asdict(generation.limits)})
    deadline = time.monotonic() + timeout_seconds
    generated = None
    source_error = None
    payload = None
    checked_value = None
    backend = None
    hit = False

    def check(value):
        nonlocal payload, checked_value
        # procache checks before and after taking a flight. A candidate runs the
        # task predicate once per operation, including when it is rejected.
        if value == checked_value:
            return payload is not None
        checked_value = value
        payload = _decode(value, key, config, routes, messages, response_format)
        if payload is None:
            return False
        candidate = _candidate(payload, key)
        try:
            validate_response(candidate, response_format, gate)
        except _RetryableAttemptError:
            payload = None
            return False
        return True

    def load():
        nonlocal generated, source_error
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CompletionError("completion cache wait timed out", diagnostic_code="SUBLLM-CACHE-TIMEOUT")
        try:
            generated = invoke(routes, remaining)
        except BaseException as error:
            source_error = error
            raise
        return _encode(generated, key)

    try:
        backend = _open_cache(config, deadline, check)
        value, hit = backend.get_or_set(key, load, ttl=config.ttl, should_cache=bool)
        if hit:
            return _replay(payload, key, routes, messages, response_format, capture, generation)
        source = json.loads(value) if value else None
        return replace(generated, cache=_receipt("miss" if source else "bypass", key, source))
    except Exception as error:
        if source_error is not None:
            raise source_error from None
        if generated is not None:
            return replace(generated, cache=_receipt("unavailable", key))
        if hit or isinstance(error, CompletionError):
            raise
        return replace(invoke(routes, max(0, deadline - time.monotonic())),
                       cache=_receipt("unavailable", key))
    except BaseException:
        if source_error is not None:
            raise source_error from None
        raise
    finally:
        if backend is not None:
            # Closing cache storage never invalidates a completed operation.
            with suppress(Exception):
                backend.close()
