"""Context-local per-attempt capture, enabled only inside the private gateway."""

from __future__ import annotations

import logging
from contextvars import ContextVar

from .gateway_diagnostics import diagnostic

ACTIVE_ARCHIVE = ContextVar("subllm_interaction_archive", default=None)
LOG = logging.getLogger(__name__)


def begin_attempt(route, messages, response_format):
    context = ACTIVE_ARCHIVE.get()
    if context is None:
        return None
    store, parent = context
    record = store.begin(
        kind="llm_attempt",
        caller=parent["caller"],
        target=route.wire_model,
        request={
            "messages": list(messages),
            "response_format": response_format,
            "model_parameters": dict(route.model_parameters),
        },
        correlation_id=parent["id"],
    )
    return store, record


def finish_attempt(entry, route, response, error, duration_ms):
    if entry is None:
        return
    store, record = entry
    outcome = getattr(error, "outcome", "unknown") if error else "success"
    info = None
    if error:
        code = {
            "http_401": "SUBLLM-UPSTREAM-AUTH",
            "http_403": "SUBLLM-UPSTREAM-AUTH",
            "http_429": "SUBLLM-UPSTREAM-LIMIT",
            "http_402": "SUBLLM-UPSTREAM-LIMIT",
            "timeout": "SUBLLM-UPSTREAM-TIMEOUT",
            "transport_error": "SUBLLM-UPSTREAM-TRANSPORT",
        }.get(outcome, "SUBLLM-LLM-EXECUTION")
        status = int(outcome[5:]) if outcome.startswith("http_") and outcome[5:].isdigit() else None
        info = diagnostic(code, duration_ms=duration_ms, http_status=status)
    payload = (
        {
            "content": response.content,
            "usage": dict(response.usage),
            "raw": dict(response.raw),
            "finish_reason": response.finish_reason,
        }
        if response
        else {"outcome": outcome, "exchange": getattr(error, "private_exchange", {})}
    )
    try:
        store.finish(
            record,
            payload,
            duration_ms=duration_ms,
            diagnostic=info,
            metadata={
                "provider": route.provider,
                "model": route.wire_model,
                "application": route.application,
                "function": route.function,
                "parent_id": record["correlation_id"],
            },
        )
    except Exception:
        LOG.error("SUBLLM-ARCHIVE-WRITE: attempt result not persisted; no upstream retry")
