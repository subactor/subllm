"""Immutable completion receipts observed at the existing native commit boundaries.

No storage is written here. ``stored`` means every enabled backend acknowledged
its write; ``unavailable`` preserves any references that did commit. An archive
without configuration is ``disabled``. A response without observed attempts has
disabled audit; legacy, manually constructed responses retain ``audit=None``.
Journal IDs resolve through usage.query_interaction_detail in the same profile.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

AuditState = Literal["stored", "unavailable", "disabled"]


def _state(states) -> AuditState:
    if "unavailable" in states:
        return "unavailable"
    return "stored" if "stored" in states else "disabled"


@dataclass(frozen=True, slots=True)
class ArchiveReference:
    id: str
    day: str
    correlation_id: str


@dataclass(frozen=True, slots=True)
class JournalReference:
    id: str
    request_id_hash: str


@dataclass(frozen=True, slots=True)
class AuditAttempt:
    application: str
    function: str
    provider: str
    model: str
    status: str
    archive_state: AuditState
    journal_state: AuditState
    archive: ArchiveReference | None = None
    journal: JournalReference | None = None
    state: AuditState = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "state", _state((self.archive_state, self.journal_state)))


@dataclass(frozen=True, slots=True)
class CompletionAudit:
    request_id: str
    correlation_id: str
    attempts: tuple[AuditAttempt, ...] = ()
    state: AuditState = field(init=False)

    def __post_init__(self):
        object.__setattr__(self, "attempts", tuple(self.attempts))
        object.__setattr__(self, "state", _state(tuple(attempt.state for attempt in self.attempts)))


@dataclass
class _Observation:
    identity: tuple
    status: str = "error"
    archive_state: AuditState = "unavailable"
    journal_state: AuditState = "unavailable"
    archive: ArchiveReference | None = None
    journal: JournalReference | None = None

    def receipt(self):
        return AuditAttempt(*self.identity[1:], self.status, self.archive_state,
                            self.journal_state, self.archive, self.journal)


@dataclass
class _Capture:
    request_id: str
    correlation_id: str
    attempts: list[AuditAttempt] = field(default_factory=list)

    def receipt(self):
        return CompletionAudit(self.request_id, self.correlation_id, tuple(self.attempts))


_REQUEST = ContextVar("subllm_audit_request", default=None)
_ATTEMPT = ContextVar("subllm_audit_attempt", default=None)


@contextmanager
def capture_audit(request_id, correlation_id):
    capture = _Capture(request_id, correlation_id)
    token = _REQUEST.set(capture)
    attempt_token = _ATTEMPT.set(None)
    try:
        yield capture
    finally:
        _ATTEMPT.reset(attempt_token)
        _REQUEST.reset(token)


@contextmanager
def audit_attempt(request_id, route):
    capture = _REQUEST.get()
    if capture is None or capture.request_id != request_id:
        yield None
        return
    observation = _Observation((request_id, route.application, route.function, route.provider, route.wire_model))
    token = _ATTEMPT.set(observation)
    try:
        yield observation
    finally:
        _ATTEMPT.reset(token)
        capture.attempts.append(observation.receipt())


def observe_archive(identity, state, reference=None):
    observation = _ATTEMPT.get()
    if observation is not None and observation.identity == identity:
        observation.archive_state, observation.archive = state, reference


def observe_journal(identity, state, reference=None):
    observation = _ATTEMPT.get()
    if observation is not None and observation.identity == identity:
        observation.journal_state, observation.journal = state, reference
