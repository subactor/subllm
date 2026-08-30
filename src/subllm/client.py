from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .errors import (
    PROVIDER_CHAIN_EXHAUSTED_CODE,
    PROVIDER_RATE_LIMIT_CODE,
    PROVIDER_UNAVAILABLE_CODE,
    CompletionError,
)
from .health import order_by_health, record_failure, record_success
from .policy_config import load_policy_config
from .resolver import available_routes, configured_routes
from .types import ResolvedRoute

MAX_VISION_DATA_URL_CHARS = 4_000_000
MAX_COMPLETION_REQUEST_BYTES = 1_000_000
_IMAGE_URL_PREFIXES = ("data:image/", "https://")


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
    def __init__(self, message: str, *, outcome: str, provider_level: bool = True) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.provider_level = provider_level


def _attempt_diagnostic_code(outcome: str) -> str:
    if outcome == "http_429":
        return PROVIDER_RATE_LIMIT_CODE
    return PROVIDER_UNAVAILABLE_CODE


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


def _image_url(part: Mapping[str, Any]) -> str:
    payload = part.get("image_url")
    if isinstance(payload, str):
        return payload
    if isinstance(payload, Mapping):
        return str(payload.get("url") or "")
    return ""


def _iter_image_urls(messages: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    urls: list[str] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping) or part.get("type") != "image_url":
                continue
            urls.append(_image_url(part))
    return tuple(urls)


def _validate_vision_messages(messages: Sequence[Mapping[str, Any]], *, modality: str) -> None:
    urls = _iter_image_urls(messages)
    if urls and modality != "vision":
        raise CompletionError("image content requires a vision SubLLM route")
    if modality != "vision":
        return
    if not urls:
        raise CompletionError("vision route requires at least one image_url part")
    for url in urls:
        if not url.startswith(_IMAGE_URL_PREFIXES):
            raise CompletionError("vision image_url must be an https or data:image URL")
        if url.startswith("data:image/") and len(url) > MAX_VISION_DATA_URL_CHARS:
            raise CompletionError("vision data URL exceeds the size limit")


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
    option_values = {
        "model": cursor["model"],
        "api_key": cursor["api_key"],
        "local": LocalAgentOptions(cwd=str(cwd), setting_sources=[]),
        "tools": [],
        "name": f"subllm-{route.application}-{route.function}",
    }
    options = AgentOptions(**option_values)
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


def _complete_openai_compatible(
    route: ResolvedRoute,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float,
    request_id: str | None,
    response_format: Mapping[str, Any] | None,
) -> CompletionResponse:
    body: dict[str, Any] = {
        "model": route.wire_model,
        "messages": [dict(message) for message in messages],
        **dict(route.model_parameters),
        **route.provider_request_fields(request_id=request_id),
    }
    if response_format is not None:
        body["response_format"] = dict(response_format)
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
        message = f"{route.provider}/{route.wire_model} request failed with HTTP {exc.code}"
        if exc.code in {401, 403, 408, 409, 425, 429} or exc.code >= 500:
            raise _RetryableAttemptError(
                message,
                outcome=f"http_{exc.code}",
                provider_level=exc.code != 404,
            ) from exc
        if exc.code == 404:
            raise _RetryableAttemptError(
                message,
                outcome="model_unavailable",
                provider_level=False,
            ) from exc
        raise CompletionError(message) from exc
    except (TimeoutError, URLError, OSError) as exc:
        outcome = "timeout" if isinstance(exc, TimeoutError) else "transport_error"
        raise _RetryableAttemptError(
            f"{route.provider}/{route.wire_model} request failed: {type(exc).__name__}",
            outcome=outcome,
        ) from exc
    try:
        return _decode_response(payload, provider=route.provider, model=route.wire_model)
    except CompletionError as exc:
        raise _RetryableAttemptError(
            str(exc),
            outcome="invalid_response",
            provider_level=False,
        ) from exc


def _complete_route(
    route: ResolvedRoute,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float,
    request_id: str | None,
    response_format: Mapping[str, Any] | None,
    cwd: Path,
) -> CompletionResponse:
    if route.transport == "cursor-sdk":
        try:
            return _complete_cursor(route, messages, timeout_seconds=timeout_seconds, cwd=cwd)
        except CompletionError as exc:
            raise _RetryableAttemptError(
                str(exc),
                outcome="provider_unavailable",
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
            attempts.append(CompletionAttempt(
                route.provider,
                route.wire_model,
                exc.outcome,
                round(duration * 1000),
                _attempt_diagnostic_code(exc.outcome),
            ))
            record_failure(
                route.provider,
                reason=exc.outcome,
                latency_seconds=duration,
                policy=execution,
            )
            if exc.provider_level:
                failed_providers.add(route.provider)
            last_error = exc
            if not execution.failover_enabled:
                raise CompletionError(
                    str(exc),
                    diagnostic_code=_attempt_diagnostic_code(exc.outcome),
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


def execute_code_edit(
    application: str,
    function: str,
    prompt: str,
    *,
    worktree: str | Path,
    provider: str | None = None,
    aider_bin: str = "aider",
    timeout_seconds: float = 2700.0,
    environ: Mapping[str, str] | None = None,
) -> CodeEditResponse:
    """Run one policy-routed OpenAI-compatible model through fixed Aider editing.

    SubLLM owns provider/model/credential resolution.  The credential is passed
    only in the child environment, never in argv, output, or an artifact.
    Aider cannot commit, run tests, or use an interactive shell in this adapter.
    """
    root = Path(worktree).resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise CompletionError("code edit worktree must be an existing Git worktree")
    if not prompt.strip() or len(prompt.encode("utf-8")) > 1_000_000:
        raise CompletionError("code edit prompt must contain 1 to 1000000 UTF-8 bytes")
    if Path(aider_bin).name != "aider":
        raise CompletionError("code edit adapter requires an aider executable")
    routes = [
        route for route in available_routes(application, function, environ=environ)
        if route.transport == "openai-compatible" and (provider is None or route.provider == provider)
    ]
    if not routes:
        raise CompletionError(
            f"no available OpenAI-compatible route for {application}/{function}"
        )
    route = routes[0]
    child_environment = dict(os.environ if environ is None else environ)
    child_environment.update({
        "AIDER_ANALYTICS": "false",
        "AIDER_OPENAI_API_BASE": route.api_base,
        "AIDER_OPENAI_API_KEY": route.api_key,
        "AIDER_MODEL": f"openai/{route.wire_model}",
    })
    with tempfile.TemporaryDirectory(prefix="subllm-aider-") as temporary:
        command = [
            aider_bin,
            "--message", prompt,
            "--yes-always",
            "--no-auto-commits",
            "--no-dirty-commits",
            "--no-auto-lint",
            "--no-auto-test",
            "--no-check-update",
            "--no-gitignore",
            "--map-tokens", "0",
            "--no-analytics",
            "--chat-history-file", str(Path(temporary) / "chat.history"),
            "--input-history-file", str(Path(temporary) / "input.history"),
        ]
        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=child_environment,
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CompletionError(
                f"{route.provider}/{route.wire_model} Aider execution failed: {type(exc).__name__}"
            ) from exc
    if completed.returncode != 0:
        raise CompletionError(
            f"{route.provider}/{route.wire_model} Aider exited with status {completed.returncode}"
        )
    return CodeEditResponse(
        provider=route.provider,
        model=route.wire_model,
        response=(completed.stdout or "")[-100_000:],
    )


def code_edit_main(argv: Sequence[str] | None = None) -> int:
    """Dedicated, closed CLI adapter for governed coding-agent execution."""
    parser = argparse.ArgumentParser(prog="subllm-code-edit")
    parser.add_argument("application")
    parser.add_argument("function")
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--provider")
    parser.add_argument("--aider-bin", default="aider")
    parser.add_argument("--timeout", type=float, default=2700.0)
    args = parser.parse_args(argv)
    try:
        prompt = args.prompt_file.read_text(encoding="utf-8")
        result = execute_code_edit(
            args.application,
            args.function,
            prompt,
            worktree=args.worktree,
            provider=args.provider,
            aider_bin=args.aider_bin,
            timeout_seconds=args.timeout,
        )
    except (OSError, UnicodeError, CompletionError) as exc:
        print(f"subllm-code-edit: {exc}")
        return 2
    print(json.dumps({
        "schema": "subllm.code-edit-result/v1",
        "status": "SUCCESS",
        "provider": result.provider,
        "model": result.model,
        "response": result.response,
    }, ensure_ascii=False, sort_keys=True))
    return 0


def _completion_timeout(value: str) -> float:
    try:
        timeout = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timeout must be a number") from exc
    if not 0 < timeout <= 900:
        raise argparse.ArgumentTypeError("timeout must be greater than 0 and at most 900 seconds")
    return timeout


def _completion_request(source: Any) -> tuple[list[Mapping[str, Any]], str | None, Mapping[str, Any] | None]:
    if not isinstance(source, Mapping) or set(source) - {
        "schema", "messages", "request_id", "response_format",
    }:
        raise CompletionError("completion request must be a closed JSON object")
    if source.get("schema") != "subllm.completion-request/v1":
        raise CompletionError("completion request schema is not supported")
    messages = source.get("messages")
    if (
        not isinstance(messages, list)
        or not 1 <= len(messages) <= 128
        or any(not isinstance(message, Mapping) for message in messages)
    ):
        raise CompletionError("completion request messages must contain 1 to 128 objects")
    request_id = source.get("request_id")
    if request_id is not None and (
        not isinstance(request_id, str)
        or not 6 <= len(request_id) <= 64
        or any(character in request_id for character in "\r\n\x00")
    ):
        raise CompletionError("completion request_id must contain 6 to 64 safe characters")
    response_format = source.get("response_format")
    if response_format is not None and not isinstance(response_format, Mapping):
        raise CompletionError("completion response_format must be an object")
    return messages, request_id, response_format


def completion_main(argv: Sequence[str] | None = None) -> int:
    """Closed stdin-JSON adapter for policy-owned completion and failover."""
    parser = argparse.ArgumentParser(prog="subllm-complete")
    parser.add_argument("application")
    parser.add_argument("function")
    parser.add_argument("--timeout", type=_completion_timeout, default=30.0)
    args = parser.parse_args(argv)
    try:
        encoded = sys.stdin.buffer.read(MAX_COMPLETION_REQUEST_BYTES + 1)
        if len(encoded) > MAX_COMPLETION_REQUEST_BYTES:
            raise CompletionError("completion request exceeds 1000000 bytes")
        request = json.loads(encoded.decode("utf-8"))
        messages, request_id, response_format = _completion_request(request)
        result = complete(
            args.application,
            args.function,
            messages,
            timeout_seconds=args.timeout,
            request_id=request_id,
            response_format=response_format,
        )
    except (UnicodeError, json.JSONDecodeError, CompletionError) as exc:
        print(f"subllm-complete: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "schema": "subllm.completion-result/v1",
        "status": "SUCCESS",
        "content": result.content,
        "provider": result.provider,
        "model": result.model,
        "usage": dict(result.usage),
        "finish_reason": result.finish_reason,
        "attempts": [asdict(attempt) for attempt in result.attempts],
    }, ensure_ascii=False, sort_keys=True))
    return 0


__all__ = [
    "CodeEditResponse", "CompletionAttempt", "CompletionResponse", "code_edit_main", "complete",
    "completion_main", "execute_code_edit",
]
