from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .errors import (
    CURSOR_WORKER_TIMEOUT_CODE,
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
MAX_CURSOR_WORKER_RESULT_BYTES = 1_000_000
MAX_OPENAI_WORKER_RESULT_BYTES = 1_000_000
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


def _terminate_worker_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate an isolated attempt worker and every descendant."""
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGTERM)
        else:  # pragma: no cover - production runners are POSIX
            process.terminate()
    except ProcessLookupError:
        return
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=1.0)
    try:
        if os.name == "posix":
            # The worker may have exited while its bridge descendants retained
            # the process group, so always reap the remaining group members.
            os.killpg(process.pid, signal.SIGKILL)
        else:  # pragma: no cover - production runners are POSIX
            process.kill()
    except ProcessLookupError:
        pass
    process.wait()


def _run_cursor_worker(
    request: Mapping[str, Any],
    *,
    timeout_seconds: float,
    cwd: Path,
) -> Mapping[str, Any]:
    encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    process = subprocess.Popen(  # noqa: S603 - fixed interpreter/module invocation
        [sys.executable, "-m", "subllm.cursor_worker"],
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(input=encoded, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_worker_process_group(process)
        raise CompletionError(
            f"Cursor SDK worker timed out after {timeout_seconds:g}s",
            diagnostic_code=CURSOR_WORKER_TIMEOUT_CODE,
        ) from exc
    if process.returncode != 0:
        raise CompletionError("Cursor SDK worker failed")
    if len(output) > MAX_CURSOR_WORKER_RESULT_BYTES:
        raise CompletionError("Cursor SDK worker result exceeds 1000000 bytes")
    try:
        result = json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompletionError("Cursor SDK worker returned invalid JSON") from exc
    if not isinstance(result, Mapping) or set(result) != {
        "schema", "status", "content", "usage", "finish_reason", "run_id",
    }:
        raise CompletionError("Cursor SDK worker returned an invalid result")
    if result.get("schema") != "subllm.cursor-worker-result/v1" or result.get("status") != "SUCCESS":
        raise CompletionError("Cursor SDK worker did not return success")
    if not isinstance(result.get("content"), str) or not result["content"]:
        raise CompletionError("Cursor SDK worker returned empty content")
    if not isinstance(result.get("usage"), Mapping):
        raise CompletionError("Cursor SDK worker returned invalid usage")
    return result


def _complete_cursor(
    route: ResolvedRoute,
    messages: Sequence[Mapping[str, Any]],
    *,
    timeout_seconds: float,
    cwd: Path,
) -> CompletionResponse:
    """Execute Cursor in a bounded process group without tools or shell access."""
    cursor = route.cursor_sdk_kwargs()
    result = _run_cursor_worker(
        {
            "schema": "subllm.cursor-worker-request/v1",
            "model": cursor["model"],
            "api_key": cursor["api_key"],
            "cwd": str(cwd),
            "name": f"subllm-{route.application}-{route.function}",
            "prompt": _message_text(messages),
        },
        timeout_seconds=timeout_seconds,
        cwd=cwd,
    )
    return CompletionResponse(
        content=str(result["content"]),
        provider=route.provider,
        model=route.wire_model,
        usage=dict(result["usage"]),
        finish_reason=str(result["finish_reason"]),
        raw={
            "transport": "cursor-sdk",
            "run_id": str(result["run_id"]),
            "status": "finished",
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
    result = _run_openai_worker(
        {
            "schema": "subllm.openai-worker-request/v1",
            "provider": route.provider,
            "api_base": route.api_base,
            "wire_model": route.wire_model,
            "api_key": route.api_key,
            "messages": [dict(message) for message in messages],
            "model_parameters": dict(route.model_parameters),
            "request_fields": dict(route.provider_request_fields(request_id=request_id)),
            "extra_headers": dict(route.extra_headers),
            "response_format": dict(response_format) if response_format is not None else None,
        },
        timeout_seconds=timeout_seconds,
    )
    if result["status"] == "ERROR":
        outcome = str(result["outcome"])
        status = outcome.removeprefix("http_") if outcome.startswith("http_") else ""
        message = (
            f"{route.provider}/{route.wire_model} request failed with HTTP {status}"
            if status
            else f"{route.provider}/{route.wire_model} request failed: {outcome}"
        )
        if not result["retryable"]:
            raise CompletionError(message)
        raise _RetryableAttemptError(
            message,
            outcome=outcome,
            provider_level=bool(result["provider_level"]),
        )
    return CompletionResponse(
        content=str(result["content"]),
        provider=route.provider,
        model=route.wire_model,
        usage=dict(result["usage"]),
        finish_reason=str(result["finish_reason"]),
    )


def _run_openai_worker(
    request: Mapping[str, Any],
    *,
    timeout_seconds: float,
) -> Mapping[str, Any]:
    encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    process = subprocess.Popen(  # noqa: S603 - fixed interpreter/module invocation
        [sys.executable, "-m", "subllm.openai_worker"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(input=encoded, timeout=timeout_seconds)
    except subprocess.TimeoutExpired as exc:
        _terminate_worker_process_group(process)
        raise _RetryableAttemptError(
            f"OpenAI-compatible worker timed out after {timeout_seconds:g}s",
            outcome="timeout",
        ) from exc
    if process.returncode != 0:
        raise _RetryableAttemptError("OpenAI-compatible worker failed", outcome="transport_error")
    if len(output) > MAX_OPENAI_WORKER_RESULT_BYTES:
        raise _RetryableAttemptError(
            "OpenAI-compatible worker result exceeds 1000000 bytes",
            outcome="invalid_response",
            provider_level=False,
        )
    try:
        result = json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _RetryableAttemptError(
            "OpenAI-compatible worker returned invalid JSON",
            outcome="invalid_response",
            provider_level=False,
        ) from exc
    success_fields = {"schema", "status", "content", "usage", "finish_reason"}
    error_fields = {"schema", "status", "outcome", "provider_level", "retryable"}
    if not isinstance(result, Mapping) or set(result) not in (success_fields, error_fields):
        raise _RetryableAttemptError(
            "OpenAI-compatible worker returned an invalid result",
            outcome="invalid_response",
            provider_level=False,
        )
    if result.get("schema") != "subllm.openai-worker-result/v1":
        raise _RetryableAttemptError(
            "OpenAI-compatible worker result schema is not supported",
            outcome="invalid_response",
            provider_level=False,
        )
    if result.get("status") == "SUCCESS":
        if not isinstance(result.get("content"), str) or not result["content"]:
            raise _RetryableAttemptError(
                "OpenAI-compatible worker returned empty content",
                outcome="invalid_response",
                provider_level=False,
            )
        if not isinstance(result.get("usage"), Mapping):
            raise _RetryableAttemptError(
                "OpenAI-compatible worker returned invalid usage",
                outcome="invalid_response",
                provider_level=False,
            )
        if not isinstance(result.get("finish_reason"), str):
            raise _RetryableAttemptError(
                "OpenAI-compatible worker returned invalid finish reason",
                outcome="invalid_response",
                provider_level=False,
            )
    elif result.get("status") == "ERROR":
        if (
            not isinstance(result.get("outcome"), str)
            or not result["outcome"]
            or type(result.get("provider_level")) is not bool
            or type(result.get("retryable")) is not bool
        ):
            raise _RetryableAttemptError(
                "OpenAI-compatible worker returned invalid error evidence",
                outcome="invalid_response",
                provider_level=False,
            )
    else:
        raise _RetryableAttemptError(
            "OpenAI-compatible worker returned invalid status",
            outcome="invalid_response",
            provider_level=False,
        )
    return result


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
