"""Output-token limits and reservations shared by native generation attempts.

Budgets count generated output, including provider-reported reasoning, rather
than input tokens or currency. Missing usage is unknown and closes a budget to
new reservations. A failed transport is never assumed to have consumed zero.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from threading import Lock

from .errors import CompletionError

MAX_TOKEN_LIMIT = 1_000_000
SUPPORTED_TRANSPORTS = frozenset({"openai-compatible", "anthropic", "gemini-sdk"})


def _error(reason):
    return CompletionError("generation limit: " + reason.lower().replace("_", " "),
                           diagnostic_code="SUBLLM-GENERATION-" + reason.replace("_", "-"))


def token_limit(value, *, legacy_string=False):
    if legacy_string and isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 7:
        value = int(value)
    if type(value) is not int or not 1 <= value <= MAX_TOKEN_LIMIT:
        raise _error("INVALID_LIMIT")
    return value


@dataclass(frozen=True, slots=True)
class GenerationLimits:
    """Positive integer caps (1..1,000,000); None inherits the operator ceiling.

    max_output_tokens caps each attempt; max_total_output_tokens caps the request
    across all attempts. Neither includes input tokens or expresses currency.
    """

    max_output_tokens: int | None = None
    max_total_output_tokens: int | None = None

    def __post_init__(self):
        for value in (self.max_output_tokens, self.max_total_output_tokens):
            if value is not None:
                token_limit(value)


@dataclass(frozen=True, slots=True)
class GenerationUsage:
    """Immutable request accounting; unknown output remains None, never zero."""

    output_tokens: int | None
    attempts: int
    max_output_tokens: int | None
    max_total_output_tokens: int | None
    remaining_output_tokens: int | None
    remaining_campaign_tokens: int | None


class GenerationBudget:
    """Reusable output allowance (1..1,000,000), including concurrent reservations.

    Pass the same object to each call joining a campaign. Operator ceilings still
    apply to each request. Unknown usage makes output_tokens/remaining_tokens
    None and prevents further dispatch through this budget.
    """

    def __init__(self, total_output_tokens: int):
        self._limit = token_limit(total_output_tokens)
        self._spent = self._reserved = 0
        self._unknown = False
        self._lock = Lock()

    @property
    def total_output_tokens(self):
        return self._limit

    @property
    def output_tokens(self):
        with self._lock:
            return None if self._unknown else self._spent

    @property
    def remaining_tokens(self):
        with self._lock:
            return None if self._unknown else max(0, self._limit - self._spent - self._reserved)


def output_count(usage):
    if not isinstance(usage, Mapping):
        return None
    if "generation_output_tokens" in usage:
        value = usage["generation_output_tokens"]
        return value if type(value) is int and value >= 0 else None
    values = [usage[key] for key in ("output_tokens", "completion_tokens") if key in usage]
    if not values or any(type(v) is not int or v < 0 for v in values) or len(set(values)) != 1:
        return None
    return values[0]


class _Scope:
    def __init__(self, limits, campaign, execution):
        if isinstance(limits, Mapping):
            if set(limits) - {"max_output_tokens", "max_total_output_tokens"}:
                raise _error("INVALID_LIMIT")
            limits = GenerationLimits(**limits)
        if limits is not None and not isinstance(limits, GenerationLimits):
            raise _error("INVALID_LIMIT")
        if campaign is not None and not isinstance(campaign, GenerationBudget):
            raise _error("INVALID_BUDGET")
        requested = limits or GenerationLimits()
        effective = {}
        for name in ("max_output_tokens", "max_total_output_tokens"):
            operator = getattr(execution, name, None)
            caller = getattr(requested, name)
            if operator is not None and caller is not None and caller > operator:
                raise _error("POLICY_LIMIT")
            effective[name] = caller if caller is not None else operator
        self.limits = GenerationLimits(**effective)
        self.request = (GenerationBudget(self.limits.max_total_output_tokens)
                        if self.limits.max_total_output_tokens is not None else None)
        self.campaign = campaign
        self.attempts = self.spent = 0
        self.unknown = False
        self.active = bool(self.limits.max_output_tokens is not None or self.request or campaign)

    def receipt(self):
        if not self.active:
            return None
        return GenerationUsage(None if self.unknown else self.spent, self.attempts,
                               self.limits.max_output_tokens, self.limits.max_total_output_tokens,
                               self.request.remaining_tokens if self.request is not None else None,
                               self.campaign.remaining_tokens if self.campaign is not None else None)


_CURRENT = ContextVar("subllm_generation_scope", default=None)


def generation_accounting_active():
    scope = _CURRENT.get()
    return scope is not None and scope.active


@contextmanager
def generation_scope(limits, budget, execution):
    scope = _Scope(limits, budget, execution)
    token = _CURRENT.set(scope)
    try:
        yield scope
    finally:
        _CURRENT.reset(token)


class _Reservation:
    def __init__(self, route, scope):
        self.scope = scope
        self.dispatched = self.settled = False
        route_limit = route.model_parameters.get("max_tokens")
        route_limit = token_limit(route_limit, legacy_string=True) if route_limit is not None else None
        caps = [v for v in (scope.limits.max_output_tokens, route_limit) if v is not None]
        self.budgets = tuple(sorted((b for b in (scope.request, scope.campaign) if b is not None), key=id))
        with ExitStack() as locks:
            for budget in self.budgets:
                locks.enter_context(budget._lock)
                if budget._unknown:
                    raise _error("USAGE_UNKNOWN")
                caps.append(max(0, budget._limit - budget._spent - budget._reserved))
            self.cap = min(caps) if caps else None
            if self.cap == 0:
                raise _error("BUDGET_EXHAUSTED")
            if self.cap is not None and route.transport not in SUPPORTED_TRANSPORTS:
                raise _error("UNSUPPORTED_TRANSPORT")
            self.route = (replace(route, model_parameters={**route.model_parameters, "max_tokens": str(self.cap)})
                          if self.cap is not None else route)
            for budget in self.budgets:
                budget._reserved += self.cap
        scope.active |= self.cap is not None

    def finish(self, usage):
        if self.settled:
            return
        self.settled = True
        count = output_count(usage) if self.dispatched else 0
        with ExitStack() as locks:
            for budget in self.budgets:
                locks.enter_context(budget._lock)
            for budget in self.budgets:
                budget._reserved -= self.cap
                budget._unknown |= count is None
                if count is not None:
                    budget._spent += count
        if self.dispatched:
            self.scope.attempts += 1
            self.scope.unknown |= count is None
            if count is not None:
                self.scope.spent += count
            if self.cap is not None and count is not None and count > self.cap:
                raise _error("LIMIT_EXCEEDED")


@contextmanager
def generation_attempt(route, policy_file=None):
    scope = _CURRENT.get()
    if scope is None:
        from .policy_config import load_policy_config

        env = {**os.environ, **({"SUBLLM_POLICY_FILE": str(policy_file)} if policy_file else {})}
        execution = load_policy_config(environ=env).execution
        if execution.max_total_output_tokens is not None:
            raise _error("REQUEST_SCOPE_REQUIRED")
        with generation_scope(None, None, execution), generation_attempt(route, policy_file) as reservation:
            yield reservation
        return
    reservation = _Reservation(route, scope)
    try:
        yield reservation
    finally:
        if not reservation.settled:
            reservation.finish(None)
