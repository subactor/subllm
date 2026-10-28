"""Private attempt capture and one-shot, identity-bound journal attribution."""

from __future__ import annotations

import logging
from contextvars import ContextVar

from .gateway_diagnostics import diagnostic

ACTIVE_ARCHIVE = ContextVar("subllm_interaction_archive", default=None)
_NEXT_USAGE_ARCHIVE = ContextVar("subllm_next_usage_archive", default=None)
LOG = logging.getLogger(__name__)


class _AttemptRecord(dict):
    """Keep the journal subject out of serialized archive documents."""

    __slots__ = ("usage_identity",)

    def __init__(self, record, identity):
        super().__init__(record)
        self.usage_identity = identity


def _take_usage_archive_reference(request_id, application, function, provider, model):
    binding = _NEXT_USAGE_ARCHIVE.get()
    _NEXT_USAGE_ARCHIVE.set(None)
    if binding is not None and binding[0] == (request_id, application, function, provider, model):
        return {"id": binding[1][0], "day": binding[1][1]}
    return None


def begin_attempt(route, messages, response_format, request_id=None, timeout_seconds=None):
    _NEXT_USAGE_ARCHIVE.set(None)
    try:
        import uuid

        req_payload = {
            "messages": list(messages),
            "response_format": response_format,
            "model_parameters": dict(route.model_parameters),
        }
        if timeout_seconds is not None:
            req_payload["timeout_seconds"] = float(timeout_seconds)
        context = ACTIVE_ARCHIVE.get()
        if context is not None:
            store, parent = context
            caller, target, correlation = parent["caller"], route.wire_model, parent["id"]
        else:
            from .interaction_store import get_default_interaction_store

            store = get_default_interaction_store()
            if store is None:
                return None
            caller, target, correlation = route.application or "direct", f"{route.provider}/{route.wire_model}", (
                request_id or uuid.uuid4().hex
            )
        record = store.begin(
            kind="llm_attempt", caller=caller, target=target, request=req_payload, correlation_id=correlation,
        )
        identity = (request_id, *(getattr(route, key, None) for key in
                                 ("application", "function", "provider", "wire_model")))
        return store, _AttemptRecord(record, identity)
    except Exception:
        LOG.warning("SUBLLM-ARCHIVE-BEGIN: capture unavailable; upstream call preserved")
        return None


def finish_attempt(entry, route, response, error, duration_ms):
    _NEXT_USAGE_ARCHIVE.set(None)
    if entry is None:
        return
    try:
        from .usage import archive_reference

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
            {"content": response.content, "usage": dict(response.usage), "raw": dict(response.raw),
             "finish_reason": response.finish_reason}
            if response else {"outcome": outcome, "exchange": getattr(error, "private_exchange", {})}
        )
        input_tokens = output_tokens = None
        if response and getattr(response, "usage", None):
            input_tokens = response.usage.get("input_tokens") or response.usage.get("prompt_tokens")
            output_tokens = response.usage.get("output_tokens") or response.usage.get("completion_tokens")
        metadata = {
            "provider": route.provider, "model": route.wire_model,
            "application": route.application, "function": route.function,
            "parent_id": record["correlation_id"],
            "input_tokens": input_tokens, "output_tokens": output_tokens,
        }
        saved = store.finish(
            record,
            payload,
            duration_ms=duration_ms,
            diagnostic=info,
            metadata=metadata,
        )
        identity = getattr(record, "usage_identity", None)
        if saved is not None and identity and all(isinstance(v, str) and 0 < len(v) <= 256 for v in identity):
            reference = archive_reference({"id": saved["id"], "day": saved["day"]})
            if reference != {"id": record["id"], "day": record["day"]}:
                raise ValueError("Changed archive identity")
            # Gateway parents can intentionally own a different caller/correlation.
            # Preserve that graph and link only an actual same-subject attempt.
            if (saved.get("caller") == identity[1] and saved.get("correlation_id") == identity[0]
                    and identity[1:] == (route.application, route.function, route.provider, route.wire_model)):
                _NEXT_USAGE_ARCHIVE.set((identity, (reference["id"], reference["day"])))
    except Exception:
        LOG.error("SUBLLM-ARCHIVE-WRITE: capture or journal reference unavailable; no upstream retry")
