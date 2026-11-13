"""Pinned request policy, explicit audit profile and cooperative absolute lifetime.

Use ``capture_policy(environ=...)`` and ``with request_scope(policy=snapshot,
audit=RequestAuditContext(store, journal), timeout_seconds=...) as scope``.
The existing complete/stream interfaces keep their policy/quality boundaries.
Cancellation is cooperative in native pipe workers; arbitrary caller predicates
and third-party CLI code are not a sandbox or a hard real-time boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from collections.abc import Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field, fields, is_dataclass, replace
from functools import wraps
from pathlib import Path
from threading import Event
from types import MappingProxyType

from .errors import CompletionError, InvalidPolicyError

_CURRENT = ContextVar("subllm_request_scope", default=None)


def current_scope():
    return _CURRENT.get()


def request_environment():
    scope = current_scope()
    return scope.environment if scope is not None else os.environ


def verify_current():
    scope = current_scope()
    if scope is not None:
        scope.before_effect()


def bind_response(response):
    scope = current_scope()
    if scope is None:
        return response
    return replace(response, raw={**response.raw, "resolved_policy_sha256": scope.snapshot.digest})


def _primitive(value):
    if is_dataclass(value):
        return {f.name: _primitive(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: _primitive(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_primitive(v) for v in value]
    return str(value) if isinstance(value, Path) else value


def _digest(policy, providers, models):
    return hashlib.sha256(json.dumps(_primitive((policy, providers, models, catalog_digest())), sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


_CATALOG_CACHE = None


def catalog_digest():
    global _CATALOG_CACHE
    from .policy import APPLICATIONS, MODELS, PROVIDERS, ROUTES
    references = (PROVIDERS._base, MODELS._base, APPLICATIONS, ROUTES)
    cached = _CATALOG_CACHE
    if cached is None or any(a is not b for a, b in zip(references, cached[0], strict=True)):
        data = (*references[:3], tuple(ROUTES[k] for k in sorted(ROUTES)))
        digest = hashlib.sha256(json.dumps(_primitive(data), sort_keys=True, separators=(",", ":")).encode())
        cached = (references, digest.hexdigest())
        _CATALOG_CACHE = cached
    return cached[1]


@dataclass(frozen=True, slots=True, init=False)
class ResolvedPolicySnapshot:
    policy: object = field(repr=False)
    providers: Mapping = field(repr=False)
    models: Mapping = field(repr=False)
    digest: str

    def verify(self):
        if _digest(self.policy, self.providers, self.models) != self.digest:
            raise InvalidPolicyError("resolved policy snapshot changed")
        source = self.policy.source
        if source is not None:
            try:
                from .policy_config import _no_policy_symlinks
                _no_policy_symlinks(source)
                actual = hashlib.sha256(source.read_bytes()).hexdigest()
            except OSError:
                raise InvalidPolicyError("resolved policy source unavailable") from None
            if actual != self.policy.source_sha256:
                raise InvalidPolicyError("resolved policy source changed before dispatch")

    def resolve(self, application, function, *, environ=None, credentials=None):
        """Resolve through the native validator; this snapshot grants no execute authority."""
        from .resolver import available_routes
        with request_scope(policy=self, environ=environ, require_owner=False):
            return available_routes(application, function, environ=request_environment(), credentials=credentials)


def capture_policy(*, environ=None):
    from .policy import MODELS, PROVIDERS
    from .policy_config import load_policy_config

    environment = {**request_environment(), **(environ or {})}
    token = _CURRENT.set(None)
    provider_token = PROVIDERS._context.set(PROVIDERS._custom)
    model_token = MODELS._context.set(MODELS._custom)
    try:
        runtime = load_policy_config(environ=environment)
        providers, models = MappingProxyType(dict(PROVIDERS._custom)), MappingProxyType(dict(MODELS._custom))
        # Only the native parser constructs a snapshot. A serialized digest is
        # an observation, never permission to supply another execution policy.
        snapshot = object.__new__(ResolvedPolicySnapshot)
        for name, value in (("policy", runtime), ("providers", providers), ("models", models),
                            ("digest", _digest(runtime, providers, models))):
            object.__setattr__(snapshot, name, value)
        snapshot.verify()
        return snapshot
    finally:
        MODELS._context.reset(model_token)
        PROVIDERS._context.reset(provider_token)
        _CURRENT.reset(token)


@dataclass(frozen=True, slots=True)
class RequestAuditContext:
    store: object = field(default=None, repr=False)
    journal: str | Path | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class RequestScope:
    snapshot: ResolvedPolicySnapshot
    deadline: float
    cancelled: Event = field(repr=False)
    environment: Mapping = field(repr=False)
    audit: RequestAuditContext | None = field(default=None, repr=False)
    require_owner: bool = True
    _stores: dict = field(default_factory=dict, repr=False, compare=False)

    def cancel(self):
        self.cancelled.set()

    def remaining(self):
        if self.cancelled.is_set():
            raise CompletionError("request cancelled", diagnostic_code="SUBLLM-REQUEST-CANCELLED")
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise CompletionError("request deadline expired", diagnostic_code="SUBLLM-REQUEST-DEADLINE")
        return remaining

    def before_effect(self):
        from .policy import MODELS, PROVIDERS
        self.remaining()
        self.snapshot.verify()
        if PROVIDERS._custom != self.snapshot.providers or MODELS._custom != self.snapshot.models:
            raise InvalidPolicyError("request catalog changed after resolution")
        self.remaining()


def policy_override(environ):
    scope = current_scope()
    if scope is None:
        return None
    selected = (environ or {}).get("SUBLLM_POLICY_FILE")
    if selected and Path(selected).expanduser().absolute() != scope.snapshot.policy.source:
        raise InvalidPolicyError("request cannot switch its resolved policy")
    return scope.snapshot.policy


@contextmanager
def request_scope(*, policy=None, environ=None, audit=None, timeout_seconds=30, cancel=None, require_owner=True):
    """Bound calls to one snapshot and lifetime; nesting can only shorten deadlines.

    Linux owns native workers through parent-death signals and process groups.
    Requiring that capability on another platform fails before invocation.
    No arbitrary child escaping its owned process group is supported.
    """
    from .native_http import normalize_timeout
    from .policy import MODELS, PROVIDERS

    if require_owner and sys.platform != "linux":
        raise CompletionError("Linux worker ownership is unavailable")
    if policy is not None and not isinstance(policy, ResolvedPolicySnapshot):
        raise InvalidPolicyError("invalid resolved policy snapshot")
    if cancel is not None and not isinstance(cancel, Event):
        raise CompletionError("invalid cancellation event")
    parent = current_scope()
    deadline = time.monotonic() + normalize_timeout(timeout_seconds)
    if parent is not None:
        parent.remaining()
        deadline = min(deadline, parent.deadline)
    environment = {**request_environment(), **(environ or {})}
    if audit is None and parent is not None:
        audit = parent.audit
    if audit is not None and not isinstance(audit, RequestAuditContext):
        raise CompletionError("invalid request audit context")
    if audit is not None:
        from .interaction_context import ACTIVE_ARCHIVE
        caller = ACTIVE_ARCHIVE.get()
        if caller is not None and caller[0] is not audit.store:
            raise CompletionError("request audit profile conflicts with caller archive")
    if audit is not None and audit.journal is not None:
        environment["SUBLLM_USAGE_DB"] = str(audit.journal)
    snapshot = policy or (parent.snapshot if parent is not None else capture_policy(environ=environment))
    snapshot.verify()
    selected = (environ or {}).get("SUBLLM_POLICY_FILE")
    if selected and Path(selected).expanduser().absolute() != snapshot.policy.source:
        raise InvalidPolicyError("request cannot switch its resolved policy")
    if snapshot.policy.source is not None:
        environment["SUBLLM_POLICY_FILE"] = str(snapshot.policy.source)
    if parent is not None and cancel is not None and cancel is not parent.cancelled:
        raise CompletionError("nested request must share cancellation")
    scope = RequestScope(snapshot, deadline, cancel or (parent.cancelled if parent else Event()),
                         MappingProxyType(environment), audit,
                         require_owner or (parent.require_owner if parent is not None else False))
    token = _CURRENT.set(scope)
    provider_token = PROVIDERS._context.set(snapshot.providers)
    model_token = MODELS._context.set(snapshot.models)
    try:
        scope.remaining()
        yield scope
    finally:
        MODELS._context.reset(model_token)
        PROVIDERS._context.reset(provider_token)
        _CURRENT.reset(token)


def bind_complete(function):
    @wraps(function)
    def complete(*args, **kwargs):
        scope = current_scope()
        if scope is None:
            return function(*args, **kwargs)
        scope.before_effect()
        kwargs["timeout_seconds"] = min(kwargs.get("timeout_seconds", 30.0), scope.remaining())
        kwargs["environ"] = {**scope.environment, **(kwargs.get("environ") or {})}
        response = function(*args, **kwargs)
        scope.remaining()
        return bind_response(response)
    return complete
