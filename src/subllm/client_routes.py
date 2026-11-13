from __future__ import annotations

import math
import os
import time
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any
from uuid import uuid4

from .audit import audit_attempt, capture_audit
from .cli_common import CLI_EXECUTABLES
from .client_types import (
    CompletionAttempt,
    CompletionResponse,
    _attempt_diagnostic_code,
    _RetryableAttemptError,
)
from .client_vision import _validate_vision_messages
from .client_workers import _complete_cursor, _complete_openai_compatible
from .completion_cache import CompletionCache, cached_complete
from .credential_env import merged_environment
from .errors import (
    PROVIDER_CHAIN_EXHAUSTED_CODE,
    CompletionError,
    CursorRunError,
)
from .generation import GenerationBudget, GenerationLimits, generation_attempt, generation_scope
from .health import order_with_last_resort, record_failure, record_success
from .interaction_context import ACTIVE_ARCHIVE, begin_attempt, finish_attempt
from .policy_config import load_policy_config, resolve_attempt_timeout
from .quality import ResponseValidator, validate_response
from .quality_schema import declared_schema_gate, schema_gate
from .request_scope import bind_complete, bind_response, current_scope, verify_current
from .resolver import available_routes, configured_routes
from .stream_transport import (
    ACTIVE_STREAM,
    attach_capture,
    invoke_stream,
    require_supported,
    stream_error,
    supported_routes,
)
from .types import ResolvedRoute
from .usage import record_attempt

NATIVE_API_TRANSPORTS = frozenset({"gemini-sdk", "anthropic"})


def _codex_response_format(response_format):
    """Project Codex's strict wire dialect; acceptance keeps the original schema."""
    if not response_format or response_format.get("type") != "json_schema":
        return response_format
    descriptor = response_format.get("json_schema", {})
    if descriptor.get("strict") is not True:
        return response_format
    from referencing import Resource
    from referencing.jsonschema import DRAFT202012

    projected = deepcopy(dict(response_format))
    pending = [Resource.from_contents(projected["json_schema"]["schema"], default_specification=DRAFT202012)]
    while pending:
        resource = pending.pop()
        pending.extend(resource.subresources())
        if isinstance(resource.contents, dict):
            # Unsupported by Codex's strict API. declared_schema_gate still
            # enforces uniqueness, including on a later failover response.
            resource.contents.pop("uniqueItems", None)
    return projected


def _complete_native(
    route: ResolvedRoute,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float,
    response_format: Mapping[str, Any] | None,
) -> CompletionResponse:
    """Gemini API and Anthropic Messages API, with the same failure classes as the OpenAI worker."""
    from . import anthropic_api, gemini_api
    from .native_http import NativeHTTPError

    module = {"gemini-sdk": gemini_api, "anthropic": anthropic_api}[route.transport]
    try:
        content, usage, finish_reason = module.invoke(
            route.api_base, route.api_key, route.wire_model, messages, timeout_seconds,
            response_format, route.model_parameters,
        )
    except NativeHTTPError as exc:
        detail = f"HTTP {exc.status}" if exc.status else exc.outcome
        message = f"{route.provider}/{route.wire_model} request failed with {detail}"
        if exc.retryable:
            raise _RetryableAttemptError(message, outcome=exc.outcome, provider_level=exc.provider_level) from None
        raise CompletionError(message) from None
    return CompletionResponse(content, route.provider, route.wire_model, usage, finish_reason)

def _invoke_route(
    route: ResolvedRoute,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float,
    request_id: str | None,
    response_format: Mapping[str, Any] | None,
    cwd: Path,
    policy_file: Path | None = None,
) -> CompletionResponse:
    scope = current_scope()
    if scope is not None:
        scope.before_effect()
        if scope.require_owner and route.transport in CLI_EXECUTABLES:
            raise CompletionError("request ownership does not support CLI transports")
        timeout_seconds = min(timeout_seconds, scope.remaining())
    if ACTIVE_STREAM.get() is not None:
        return invoke_stream(route, messages, timeout_seconds=timeout_seconds, request_id=request_id,
                             response_format=_codex_response_format(response_format)
                             if route.provider == "codex" else response_format,
                             cwd=cwd, policy_file=policy_file)
    if route.transport in CLI_EXECUTABLES:
        from . import agy_cli, claude_cli, codex_cli, cursor_cli

        invoke = {"codex-cli": codex_cli, "claude-cli": claude_cli, "agy-cli": agy_cli,
                  "cursor-cli": cursor_cli}[route.transport].invoke
        try:
            content, usage = invoke(route.wire_model, messages, timeout_seconds, response_format)
        except CompletionError as exc:
            prefix = {"codex-cli": "SUBLLM-CODEX-", "claude-cli": "SUBLLM-CLAUDE-",
                      "agy-cli": "SUBLLM-AGY-", "cursor-cli": "SUBLLM-CURSOR-CLI-"}[route.transport]
            code = exc.diagnostic_code or ""
            outcome = {"TIMEOUT": "timeout", "UNAVAILABLE": "provider_unavailable",
                       "HTTP-429": "quota_exhausted", "FAILED": "provider_unavailable"}.get(
                           code[len(prefix):] if code.startswith(prefix) else "")
            if outcome is None:
                raise
            raise _RetryableAttemptError(str(exc), outcome=outcome, diagnostic_code=code) from exc
        return CompletionResponse(content, route.provider, route.wire_model, usage, "stop")
    if route.transport in NATIVE_API_TRANSPORTS:
        return _complete_native(route, messages, timeout_seconds=timeout_seconds, response_format=response_format)
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
            response_format=_codex_response_format(response_format) if route.provider == "codex" else response_format,
            policy_file=policy_file,
        )
    raise CompletionError(f"provider {route.provider} uses unsupported transport {route.transport}")



def _complete_route(
    route: ResolvedRoute,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float,
    request_id: str | None,
    response_format: Mapping[str, Any] | None,
    cwd: Path,
    policy_file: Path | None = None,
    quality_gate: ResponseValidator | None = None,
) -> CompletionResponse:
    require_supported(route)
    quality_gate = declared_schema_gate(response_format, quality_gate)
    with generation_attempt(route, policy_file) as reservation:
        route = reservation.route
        with audit_attempt(request_id, route) as observation:
            started = time.monotonic()
            response = None
            diagnostic = None
            attempt_error = None
            archive = begin_attempt(route, messages, response_format,
                                    request_id=request_id, timeout_seconds=timeout_seconds)
            try:
                reservation.dispatched = True
                response = _invoke_route(route, messages, timeout_seconds=timeout_seconds,
                                         request_id=request_id, response_format=response_format, cwd=cwd,
                                         policy_file=policy_file)
                reservation.finish(response.usage)
                response = bind_response(response)
                verify_current()
                validate_response(response, response_format, quality_gate)
                return replace(response, generation=reservation.scope.receipt())
            except Exception as exc:
                attempt_error = exc
                active = ACTIVE_STREAM.get()
                if active is not None:
                    response = response or getattr(exc, "partial_response", None)
                    if response is not None:
                        reservation.finish(response.usage)
                        exc.partial_response = response
                    if active.observed and isinstance(exc, _RetryableAttemptError):
                        fixed = CompletionError("stream response rejected after provider output",
                                                diagnostic_code=exc.diagnostic_code)
                        fixed.partial_response = response
                        attempt_error = fixed
                        diagnostic = fixed.diagnostic_code or "SUBLLM-STREAM-REJECTED"
                        raise fixed from None
                # Never persist exception messages, raw provider errors or headers.
                if isinstance(exc, _RetryableAttemptError):
                    diagnostic = exc.diagnostic_code or _attempt_diagnostic_code(exc.outcome)
                else:
                    diagnostic = getattr(exc, "diagnostic_code", None) or "SUBLLM-ATTEMPT-FAILED"
                raise
            finally:
                from .kpi_usage import record_provider_attempt

                duration_ms = round((time.monotonic() - started) * 1000)
                status = "success" if response is not None and attempt_error is None else "error"
                if observation is not None:
                    observation.status = status
                usage = response.usage if response is not None else {}
                record_provider_attempt(provider=route.provider, model=route.wire_model,
                                        status=status, duration_ms=duration_ms, usage=usage)
                finish_attempt(archive, route, response, attempt_error, duration_ms)
                record_attempt(request_id=request_id or uuid4().hex,
                               application=route.application, function=route.function,
                               provider=route.provider, model=route.wire_model,
                               status=status, diagnostic_code=diagnostic, duration_ms=duration_ms, usage=usage)


def _requested_model_routes(routes: list[ResolvedRoute], model: str | None) -> list[ResolvedRoute]:
    if model is None:
        return routes
    selected = [route for route in routes if model in {
        route.model, route.wire_model, route.litellm_model,
        f"{route.provider}/{route.model}", f"{route.provider}/{route.wire_model}",
    }]
    if not selected:
        raise CompletionError("requested model is not available in the configured route")
    return selected


def _complete(
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
    model: str | None = None,
    quality_gate: ResponseValidator | None = None,
    quality_schema: Mapping[str, Any] | bool | None = None,
    _runtime_policy=None,
    _routes=None,
) -> CompletionResponse:
    """Execute configured routes; an explicit model restricts, never expands, them.

    Failover remains within matching routes. The application/function alias
    retains automatic selection. Explicit models on adaptive routes currently
    fail closed instead of silently ignoring the caller's choice.

    Structural response checks run before success. A bounded quality_gate may
    supply task-specific acceptance (known IDs, schema, reference answers).
    Only True accepts a result; rejection tries the next permitted candidate.
    A broken validator aborts the request rather than charging other models.
    An optional quality_schema enforces local JSON Schema 2020-12 assertions
    before acceptance, including for CLI callers. It never changes provider
    response_format. Its self-contained contract is checked before any call.
    Pass the raw schema, for example {"type": "object", "required": ["state"]},
    rather than a provider's named schema descriptor. Format is an annotation;
    caller predicates remain responsible for domain meaning.
    A schema declared in response_format=json_schema is also enforced locally,
    in addition to any explicit quality_schema or task predicate.
    """
    if quality_gate is not None and not callable(quality_gate):
        raise CompletionError("quality_gate must be callable")
    quality_gate = schema_gate(quality_schema, quality_gate)
    if not messages:
        raise CompletionError("chat completion requires at least one message")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise CompletionError("timeout_seconds must be greater than zero")
    if model is not None:
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise CompletionError("model must be a nonempty string of at most 200 characters")
        if model == f"{application}/{function}":
            model = None

    request_id = request_id or uuid4().hex
    from . import adaptive
    adaptive_policy = adaptive.policy(environ)
    requirement = adaptive_policy and adaptive_policy.get("routes", {}).get(f"{application}/{function}")
    if requirement:
        if ACTIVE_STREAM.get() is not None:
            raise stream_error("UNSUPPORTED-ADAPTIVE")
        if model is not None:
            raise CompletionError("explicit model selection is not supported by this adaptive route")
        from .proxy import _build_model_resolved_routes
        config = {**adaptive_policy, "aliases": {**adaptive_policy.get("aliases", {}), "__route__": requirement}}
        environment = dict(merged_environment(environ=environ))
        from .policy import PROVIDERS
        for provider, credential in (credentials or {}).items():
            if provider in PROVIDERS:
                environment[PROVIDERS[provider].api_key_env] = credential
        return adaptive.execute(config, "__route__", messages,
            build_routes=lambda model: _build_model_resolved_routes(model, application, function, environ=environment),
            invoke=partial(_complete_route, quality_gate=quality_gate) if quality_gate is not None else _complete_route,
            timeout_seconds=timeout_seconds,
            response_format=response_format, request_id=request_id, cwd=Path(cwd) if cwd else None, environ=environment)
    routes = _routes if _routes is not None else available_routes(
        application, function, environ=environ, credentials=credentials,
    )
    if not routes:
        configured = configured_routes(application, function, environ=environ)
        required = ", ".join(sorted({route.api_key_env for route in configured}))
        raise CompletionError(f"no valid credential for {application}/{function}; configure one of: {required}")
    routes = _requested_model_routes(supported_routes(routes), model)
    runtime_policy = _runtime_policy or load_policy_config(environ={**os.environ, **(environ or {})})
    execution = runtime_policy.execution
    timeout_environment = merged_environment(environ=environ)
    routes = order_with_last_resort(routes, environ=timeout_environment) if execution.failover_enabled else routes[:1]
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
    attempt_budgets = tuple(resolve_attempt_timeout(
        route.provider, route.wire_model, environ=timeout_environment,
        default=execution.attempt_timeout_seconds,
    ) for route in routes)
    caller_limit = timeout_seconds
    attempts: list[CompletionAttempt] = []
    failed_providers: set[str] = set()
    last_error: CompletionError | None = None
    for route, attempt_budget in zip(routes, attempt_budgets, strict=True):
        if len(attempts) >= execution.max_attempts:
            break
        if route.provider in failed_providers:
            continue
        elapsed = time.monotonic() - started_at
        remaining = caller_limit - elapsed
        if remaining <= 0:
            break
        attempt_timeout = min(remaining, attempt_budget)
        attempt_started = time.monotonic()
        try:
            response = _complete_route(
                route,
                messages,
                timeout_seconds=attempt_timeout,
                request_id=request_id,
                response_format=response_format,
                cwd=Path(cwd) if cwd is not None else Path.cwd(),
                policy_file=runtime_policy.source,
                **({"quality_gate": quality_gate} if quality_gate is not None else {}),
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
                    environ=timeout_environment,
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
        record_success(route.provider, latency_seconds=duration, policy=execution,
                       environ=timeout_environment)
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
    model: str | None = None,
    quality_gate: ResponseValidator | None = None,
    quality_schema: Mapping[str, Any] | bool | None = None,
    generation_limits: GenerationLimits | Mapping[str, Any] | None = None,
    generation_budget: GenerationBudget | None = None,
    cache: CompletionCache | None = None,
    force_generation: bool = False,
) -> CompletionResponse:
    """Complete within policy and return immutable native persistence receipts.

    ``audit.state`` is unavailable if any enabled write failed, with successful
    references retained. Storage failure never repeats a provider invocation.
    Request/correlation IDs and per-attempt references carry no prompt, response,
    credential or storage path. Existing response fields and routing are retained.

    generation_limits caps each attempt and optionally the whole request output.
    generation_budget shares an output allowance across calls, including rejected
    attempts. Missing usage stays unknown and blocks further budgeted dispatch.
    Input tokens and currency are outside this budget. Unsupported CLI/Cursor
    limits raise before invocation; callers cannot raise operator ceilings.

    cache=CompletionCache(...) explicitly enables exact plain-text API reuse.
    It requires account scope, model revision, acceptance version and TTL. A hit
    is validated again and receives a native replay archive, zero new usage and
    separate historical source_usage. force_generation bypasses reuse. Install
    the optional cache dependency; CLI, tools, adaptive and nested gateway calls
    bypass caching. Each explicit request_id must identify a new operation.
    """
    request_id = request_id or uuid4().hex
    parent = ACTIVE_ARCHIVE.get()
    try:
        correlation_id = parent[1]["id"] if parent is not None else request_id
    except (KeyError, IndexError, TypeError):
        correlation_id = request_id
    runtime_policy = load_policy_config(environ={**os.environ, **(environ or {})})
    if cache is not None:
        # Bind the key, native archive and provider body to the same caller input.
        messages = deepcopy([dict(message) for message in messages]) if messages else messages
        response_format = deepcopy(dict(response_format)) if response_format is not None else None
        quality_schema = deepcopy(dict(quality_schema)) if isinstance(quality_schema, Mapping) else quality_schema
    with (
        generation_scope(generation_limits, generation_budget, runtime_policy.execution) as generation,
        capture_audit(request_id, correlation_id) as capture,
    ):
        attach_capture(capture, generation)
        def invoke(routes=None, timeout=timeout_seconds):
            response = _complete(
                application, function, messages, timeout_seconds=timeout,
                request_id=request_id, response_format=response_format, environ=environ,
                credentials=credentials, cwd=cwd, model=model, quality_gate=quality_gate,
                quality_schema=quality_schema, _runtime_policy=runtime_policy, _routes=routes,
            )
            return replace(response, audit=capture.receipt(), generation=generation.receipt())

        if cache is None:
            return invoke()
        return cached_complete(
            cache, invoke, application=application, function=function, messages=messages,
            response_format=response_format, environ=environ, credentials=credentials,
            model=model, quality_gate=quality_gate, quality_schema=quality_schema,
            runtime_policy=runtime_policy, generation=generation, capture=capture,
            timeout_seconds=timeout_seconds, force_generation=force_generation,
        )


complete = bind_complete(complete)
