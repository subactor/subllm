from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from .client_types import (
    CompletionAttempt,
    CompletionResponse,
    _attempt_diagnostic_code,
    _RetryableAttemptError,
)
from .client_vision import _validate_vision_messages
from .client_workers import _complete_cursor, _complete_openai_compatible
from .errors import (
    PROVIDER_CHAIN_EXHAUSTED_CODE,
    CompletionError,
    CursorRunError,
)
from .health import order_by_health, record_failure, record_success
from .policy_config import load_policy_config
from .resolver import available_routes, configured_routes
from .types import ResolvedRoute


def _complete_route(
    route: ResolvedRoute,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float,
    request_id: str | None,
    response_format: Mapping[str, Any] | None,
    cwd: Path,
) -> CompletionResponse:
    if route.transport == "codex-cli":
        from .codex_cli import invoke

        content, usage = invoke(route.wire_model, messages, timeout_seconds, response_format)
        return CompletionResponse(content, route.provider, route.wire_model, usage, "stop")
    if route.transport == "cursor-sdk":
        try:
            return _complete_cursor(route, messages, timeout_seconds=timeout_seconds, cwd=cwd)
        except CompletionError as exc:
            raise _RetryableAttemptError(
                str(exc),
                outcome="model_unavailable" if isinstance(exc, CursorRunError) else "provider_unavailable",
                provider_level=not isinstance(exc, CursorRunError),
                diagnostic_code=exc.diagnostic_code,
            ) from exc
    if route.transport == "openai-compatible":
        return _complete_openai_compatible(
            route,
            messages,
            timeout_seconds=timeout_seconds,
            request_id=request_id,
            response_format=response_format,
        )
    raise CompletionError(f"provider {route.provider} uses unsupported transport {route.transport}")


def complete(
    application: str,
    function: str,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float = 30.0,
    request_id: str | None = None,
    response_format: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
    credentials: Mapping[str, str] | None = None,
    cwd: str | Path | None = None,
) -> CompletionResponse:
    """Execute a policy-resolved chat completion with bounded runtime failover."""
    if not messages:
        raise CompletionError("chat completion requires at least one message")
    if timeout_seconds <= 0:
        raise CompletionError("timeout_seconds must be greater than zero")

    routes = available_routes(application, function, environ=environ, credentials=credentials)
    if not routes:
        configured = configured_routes(application, function, environ=environ)
        required = ", ".join(sorted({route.api_key_env for route in configured}))
        raise CompletionError(f"no valid credential for {application}/{function}; configure one of: {required}")
    runtime_policy = load_policy_config(environ=environ)
    execution = runtime_policy.execution
    routes = order_by_health(routes) if execution.failover_enabled else routes[:1]
    if not routes:
        raise CompletionError(
            f"all providers cooling down for {application}/{function}",
            diagnostic_code=PROVIDER_CHAIN_EXHAUSTED_CODE,
        )
    first_route = routes[0]
    _validate_vision_messages(messages, modality=first_route.modality)
    if first_route.modality == "vision" and first_route.transport != "openai-compatible":
        raise CompletionError("vision routes require an OpenAI-compatible transport")
    started_at = time.monotonic()
    attempts: list[CompletionAttempt] = []
    failed_providers: set[str] = set()
    last_error: CompletionError | None = None
    for route in routes:
        if len(attempts) >= execution.max_attempts:
            break
        if route.provider in failed_providers:
            continue
        elapsed = time.monotonic() - started_at
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            break
        attempt_timeout = (
            min(remaining, execution.attempt_timeout_seconds)
            if execution.failover_enabled
            else remaining
        )
        attempt_started = time.monotonic()
        try:
            response = _complete_route(
                route,
                messages,
                timeout_seconds=attempt_timeout,
                request_id=request_id,
                response_format=response_format,
                cwd=Path(cwd) if cwd is not None else Path.cwd(),
            )
        except _RetryableAttemptError as exc:
            duration = time.monotonic() - attempt_started
            diagnostic_code = exc.diagnostic_code or _attempt_diagnostic_code(
                exc.outcome
            )
            attempts.append(CompletionAttempt(
                route.provider,
                route.wire_model,
                exc.outcome,
                round(duration * 1000),
                diagnostic_code,
            ))
            if exc.provider_level:
                record_failure(
                    route.provider,
                    reason=exc.outcome,
                    latency_seconds=duration,
                    policy=execution,
                )
                failed_providers.add(route.provider)
            last_error = exc
            if not execution.failover_enabled:
                raise CompletionError(
                    str(exc),
                    diagnostic_code=diagnostic_code,
                ) from exc
            continue
        duration = time.monotonic() - attempt_started
        attempts.append(CompletionAttempt(route.provider, route.wire_model, "success", round(duration * 1000)))
        record_success(route.provider, latency_seconds=duration, policy=execution)
        return replace(response, attempts=tuple(attempts))

    summary = ", ".join(
        f"{attempt.provider}/{attempt.model}:{attempt.outcome}" for attempt in attempts
    )
    if not summary:
        summary = "total_timeout"
    message = f"all bounded candidates failed for {application}/{function}: {summary}"
    raise CompletionError(
        message,
        diagnostic_code=PROVIDER_CHAIN_EXHAUSTED_CODE,
    ) from last_error
