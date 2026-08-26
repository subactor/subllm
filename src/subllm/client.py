from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import CompletionError
from .resolver import resolve


@dataclass(frozen=True)
class CompletionResponse:
    content: str
    provider: str
    model: str
    usage: Mapping[str, Any] = field(default_factory=dict)
    finish_reason: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


def _completion_url(api_base: str) -> str:
    return f"{api_base.rstrip('/')}/chat/completions"


def _decode_response(payload: bytes, *, provider: str, model: str) -> CompletionResponse:
    try:
        raw = json.loads(payload.decode("utf-8"))
        choice = raw["choices"][0]
        content = choice["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
        raise CompletionError(
            f"{provider}/{model} returned an invalid chat completion response"
        ) from exc
    if not isinstance(content, str) or not content:
        raise CompletionError(f"{provider}/{model} returned empty assistant content")
    usage = raw.get("usage")
    return CompletionResponse(
        content=content,
        provider=provider,
        model=model,
        usage=dict(usage) if isinstance(usage, Mapping) else {},
        finish_reason=str(choice.get("finish_reason") or ""),
        raw=raw,
    )


def complete(
    application: str,
    function: str,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float = 30.0,
    request_id: str | None = None,
    environ: Mapping[str, str] | None = None,
    credentials: Mapping[str, str] | None = None,
) -> CompletionResponse:
    """Execute one policy-resolved OpenAI-compatible chat completion.

    Provider and model selection remain owned by SubLLM. A request that has
    started is never replayed automatically through another paid provider.
    """
    if not messages:
        raise CompletionError("chat completion requires at least one message")
    if timeout_seconds <= 0:
        raise CompletionError("timeout_seconds must be greater than zero")

    route = resolve(
        application,
        function,
        environ=environ,
        credentials=credentials,
    )
    if route.transport != "openai-compatible":
        raise CompletionError(
            f"provider {route.provider} uses {route.transport}; "
            "complete() only executes openai-compatible routes"
        )

    body: dict[str, Any] = {
        "model": route.wire_model,
        "messages": [dict(message) for message in messages],
        **dict(route.model_parameters),
        **route.provider_request_fields(request_id=request_id),
    }
    request = Request(
        _completion_url(route.api_base),
        data=json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {route.api_key}",
            "Content-Type": "application/json",
            **dict(route.extra_headers),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - fixed policy HTTPS base
            payload = response.read()
    except HTTPError as exc:
        raise CompletionError(
            f"{route.provider}/{route.wire_model} request failed with HTTP {exc.code}"
        ) from exc
    except (TimeoutError, URLError, OSError) as exc:
        raise CompletionError(
            f"{route.provider}/{route.wire_model} request failed: {type(exc).__name__}"
        ) from exc
    return _decode_response(
        payload,
        provider=route.provider,
        model=route.wire_model,
    )


__all__ = ["CompletionResponse", "complete"]
