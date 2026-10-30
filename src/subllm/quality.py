"""Response acceptance before success; semantic truth belongs to the task owner."""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import Any

from .client_types import CompletionResponse, _RetryableAttemptError
from .errors import RESPONSE_QUALITY_CODE, CompletionError

ResponseValidator = Callable[[CompletionResponse], bool]


def _reject(reason: str, *, outcome: str = "invalid_response") -> None:
    # Reasons are fixed identifiers. Never echo content, prompts or predicate errors.
    raise _RetryableAttemptError(
        f"response quality rejected: {reason}", outcome=outcome,
        provider_level=False, diagnostic_code=RESPONSE_QUALITY_CODE,
    )


def _nonfinite(_value: str) -> None:
    raise ValueError("nonfinite JSON")


def validate_response(
    response: CompletionResponse,
    response_format: Mapping[str, Any] | None,
    validator: ResponseValidator | None = None,
) -> None:
    """Check transport-independent shape, then the caller's task acceptance predicate.

    A predicate must explicitly return True. False means reject this model's
    answer, without making other models on the same account unavailable. A
    broken predicate is a caller error, not evidence against any model.
    """
    if not isinstance(response.content, str) or not response.content.strip():
        _reject("empty")
    if response.finish_reason in {"length", "max_tokens", "max_output_tokens", "content_filter"}:
        _reject("incomplete")
    fmt = (response_format or {}).get("type")
    if fmt in {"json_object", "json_schema"}:
        try:
            value = json.loads(response.content, parse_constant=_nonfinite)
        except (ValueError, RecursionError):
            _reject("invalid_json")
        if fmt == "json_object" and not isinstance(value, dict):
            _reject("not_json_object")
    if validator is not None:
        try:
            accepted = validator(response)
        except Exception:
            raise CompletionError(
                "task quality validator failed", diagnostic_code="SUBLLM-QUALITY-VALIDATOR-ERROR",
            ) from None
        if accepted is not True:
            _reject("task_acceptance", outcome="quality_rejected")
