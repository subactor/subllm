from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import CompletionError
from .resolver import available_routes, configured_routes
from .types import ResolvedRoute


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


def _message_text(messages: Sequence[Mapping[str, Any]]) -> str:
    """Serialize messages for Cursor's text-only SDK request API."""
    rendered: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        rendered.append(f"<{role}>\n{content}\n</{role}>")
    return "\n\n".join(rendered)


def _wait_for_cursor_run(run: Any, timeout_seconds: float) -> tuple[Any | None, str | None]:
    completed: list[Any] = []
    errors: list[BaseException] = []

    def wait() -> None:
        try:
            completed.append(run.wait())
        except BaseException as exc:  # noqa: BLE001 - converted into safe transport evidence
            errors.append(exc)

    waiter = threading.Thread(target=wait, name="subllm-cursor-run", daemon=True)
    waiter.start()
    waiter.join(timeout_seconds)
    if waiter.is_alive():
        try:
            if run.supports("cancel"):
                run.cancel()
        except Exception:  # noqa: BLE001 - timeout remains the primary failure
            pass
        return None, f"Cursor SDK run timed out after {timeout_seconds:g}s"
    if errors:
        return None, type(errors[0]).__name__
    return (completed[0] if completed else None), None


def _cursor_usage(result: Any) -> Mapping[str, Any]:
    usage = getattr(result, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, Mapping):
        return dict(usage)
    try:
        return asdict(usage)
    except TypeError:
        return {}


def _complete_cursor(
    route: ResolvedRoute,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float,
    cwd: Path,
) -> CompletionResponse:
    """Execute a selected Cursor candidate without tools or shell access."""
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError as exc:
        raise CompletionError(
            "provider cursor requires the optional dependency "
            "'subactor-subllm[cursor]'"
        ) from exc

    cursor = route.cursor_sdk_kwargs()
    options = AgentOptions(
        model=cursor["model"],
        api_key=cursor["api_key"],
        local=LocalAgentOptions(cwd=str(cwd), setting_sources=[]),
        tools=[],
        name=f"subllm-{route.application}-{route.function}",
    )
    try:
        with Agent.create(options) as agent:
            result, wait_error = _wait_for_cursor_run(agent.send(_message_text(messages)), timeout_seconds)
    except Exception as exc:  # noqa: BLE001 - do not expose SDK internals or credentials
        raise CompletionError(f"{route.provider}/{route.wire_model} Cursor SDK request failed") from exc
    if wait_error:
        raise CompletionError(f"{route.provider}/{route.wire_model} {wait_error}")
    if result is None:
        raise CompletionError(f"{route.provider}/{route.wire_model} Cursor SDK returned no result")
    status = str(getattr(getattr(result, "status", ""), "value", getattr(result, "status", ""))).lower()
    content = str(getattr(result, "result", "") or "")
    if status != "finished" or not content:
        raise CompletionError(f"{route.provider}/{route.wire_model} Cursor SDK ended with status {status or 'unknown'}")
    return CompletionResponse(
        content=content,
        provider=route.provider,
        model=route.wire_model,
        usage=_cursor_usage(result),
        raw={
            "transport": "cursor-sdk",
            "run_id": str(getattr(result, "id", "") or ""),
            "status": status,
        },
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
    cwd: str | Path | None = None,
) -> CompletionResponse:
    """Execute one policy-resolved chat completion.

    Provider, model and pre-request fallback selection remain owned by
    SubLLM. A request that has started is never replayed through another paid
    provider. Cursor receives an empty tool set.
    """
    if not messages:
        raise CompletionError("chat completion requires at least one message")
    if timeout_seconds <= 0:
        raise CompletionError("timeout_seconds must be greater than zero")

    routes = available_routes(application, function, environ=environ, credentials=credentials)
    if not routes:
        configured = configured_routes(application, function, environ=environ)
        required = ", ".join(sorted({route.api_key_env for route in configured}))
        raise CompletionError(f"no valid credential for {application}/{function}; configure one of: {required}")
    route = routes[0]
    if route.transport == "cursor-sdk":
        return _complete_cursor(
            route,
            messages,
            timeout_seconds=timeout_seconds,
            cwd=Path(cwd) if cwd is not None else Path.cwd(),
        )
    if route.transport != "openai-compatible":
        raise CompletionError(f"provider {route.provider} uses unsupported transport {route.transport}")

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
