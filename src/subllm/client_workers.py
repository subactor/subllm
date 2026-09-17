from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from .client_types import CompletionResponse, _RetryableAttemptError
from .client_vision import _message_text
from .errors import (
    CURSOR_WORKER_TIMEOUT_CODE,
    CompletionError,
    CursorRunError,
)
from .types import ResolvedRoute

MAX_CURSOR_WORKER_RESULT_BYTES = 1_000_000
MAX_OPENAI_WORKER_RESULT_BYTES = 1_000_000


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
        if len(output) <= MAX_CURSOR_WORKER_RESULT_BYTES:
            try:
                failure = json.loads(output.decode('utf-8'))
            except (ValueError, UnicodeError):
                failure = None
            if failure == {'schema': 'subllm.cursor-worker-error/v1', 'error': 'model_run_failed'}:
                raise CursorRunError('Cursor SDK model run failed')
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
