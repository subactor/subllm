from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from .errors import (
    PROVIDER_RATE_LIMIT_CODE,
    PROVIDER_UNAVAILABLE_CODE,
    CompletionError,
)


@dataclass(frozen=True)
class CompletionAttempt:
    provider: str
    model: str
    outcome: str
    duration_ms: int
    diagnostic_code: str | None = None


@dataclass(frozen=True)
class CompletionResponse:
    content: str
    provider: str
    model: str
    usage: Mapping[str, Any] = field(default_factory=dict)
    finish_reason: str = ""
    attempts: tuple[CompletionAttempt, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class CodeEditResponse:
    provider: str
    model: str
    response: str


class _RetryableAttemptError(CompletionError):
    def __init__(
        self,
        message: str,
        *,
        outcome: str,
        provider_level: bool = True,
        diagnostic_code: str | None = None,
    ) -> None:
        super().__init__(message, diagnostic_code=diagnostic_code)
        self.outcome = outcome
        self.provider_level = provider_level


def _attempt_diagnostic_code(outcome: str) -> str:
    if outcome == "http_429":
        return PROVIDER_RATE_LIMIT_CODE
    return PROVIDER_UNAVAILABLE_CODE
