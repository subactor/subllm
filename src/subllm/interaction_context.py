"""Context-local per-attempt capture, enabled only inside the private gateway."""

from __future__ import annotations

import logging
from contextvars import ContextVar

from .gateway_diagnostics import diagnostic

ACTIVE_ARCHIVE = ContextVar("subllm_interaction_archive", default=None)
LOG = logging.getLogger(__name__)


def begin_attempt(route, messages, response_format, request_id=None):
    context = ACTIVE_ARCHIVE.get()
    if context is not None:
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

    from .interaction_store import get_default_interaction_store

    store = get_default_interaction_store()
    if store is None:
        return None
    try:
        import uuid

        record = store.begin(
            kind="llm_attempt",
            caller=route.application or "direct",
            target=f"{route.provider}/{route.wire_model}",
            request={
                "messages": list(messages),
                "response_format": response_format,
                "model_parameters": dict(route.model_parameters),
            },
            correlation_id=request_id or uuid.uuid4().hex,
        )
        return store, record
    except Exception as exc:
        LOG.warning("SUBLLM-ARCHIVE-BEGIN: failed to record interaction attempt: %s", exc)
        return None


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
    input_tokens = None
    output_tokens = None
    if response and getattr(response, "usage", None):
        input_tokens = response.usage.get("input_tokens") or response.usage.get("prompt_tokens")
        output_tokens = response.usage.get("output_tokens") or response.usage.get("completion_tokens")
    metadata = {
        "provider": route.provider,
        "model": route.wire_model,
        "application": route.application,
        "function": route.function,
        "parent_id": record["correlation_id"],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    }
    try:
        store.finish(
            record,
            payload,
            duration_ms=duration_ms,
            diagnostic=info,
            metadata=metadata,
        )
    except Exception:
        LOG.error("SUBLLM-ARCHIVE-WRITE: attempt result not persisted; no upstream retry")
