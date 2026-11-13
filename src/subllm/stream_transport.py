"""Native dispatch hook and bounded stream-worker process ownership."""
from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import time
from contextlib import contextmanager, suppress
from contextvars import ContextVar

from .client_types import CompletionResponse, _RetryableAttemptError
from .client_workers import api_worker_request
from .errors import CompletionError
from .native_http import decode_response_json
from .stream_protocol import MAX_EVENT, MAX_OUTPUT, MAX_STREAM
from .worker_lifetime import stop_group, wait_exit, worker_environment

SUPPORTED = frozenset({"openai-compatible", "anthropic", "gemini-sdk"})
ACTIVE_STREAM = ContextVar("subllm_active_stream", default=None)


def stream_error(reason):
    return CompletionError(f"inference stream {reason.lower().replace('_', ' ')}",
                           diagnostic_code="SUBLLM-STREAM-" + reason)


@contextmanager
def stream_scope(controller):
    token = ACTIVE_STREAM.set(controller)
    try:
        yield
    finally:
        ACTIVE_STREAM.reset(token)


def attach_capture(capture, generation):
    active = ACTIVE_STREAM.get()
    if active is not None:
        active.capture, active.generation = capture, generation


def require_supported(route):
    if ACTIVE_STREAM.get() is not None and route.transport not in SUPPORTED:
        raise stream_error("UNSUPPORTED-TRANSPORT")


def supported_routes(routes):
    if ACTIVE_STREAM.get() is None:
        return routes
    selected = [route for route in routes if route.transport in SUPPORTED]
    if not selected:
        raise stream_error("UNSUPPORTED-TRANSPORT")
    return selected


def _worker_environment(policy_file):
    env = worker_environment()
    if policy_file is not None:
        env["SUBLLM_POLICY_FILE"] = str(policy_file)
    return env


def _write_request(process, encoded, controller, deadline):
    descriptor = process.stdin.fileno()
    os.set_blocking(descriptor, False)
    offset = 0
    with selectors.DefaultSelector() as selector:
        selector.register(descriptor, selectors.EVENT_WRITE)
        while offset < len(encoded):
            if controller.cancelled.is_set() or time.monotonic() >= deadline:
                raise stream_error("CANCELLED" if controller.cancelled.is_set() else "TIMEOUT")
            if selector.select(0.05):
                with suppress(BlockingIOError):
                    offset += os.write(descriptor, encoded[offset:offset + 8192])
    process.stdin.close()


def invoke_stream(route, messages, *, timeout_seconds, request_id, response_format, cwd, policy_file=None):
    controller = ACTIVE_STREAM.get()
    from .request_scope import current_scope
    scope = current_scope()
    if scope is not None:
        scope.before_effect()
        controller.deadline = min(controller.deadline, scope.deadline)
    controller.begin_attempt(route)
    request = api_worker_request(route, messages, timeout_seconds=timeout_seconds,
                                 request_id=request_id, response_format=response_format)
    request["schema"] = "subllm.stream-worker-request/v1"
    encoded = json.dumps(request, ensure_ascii=True, separators=(",", ":")).encode()
    if len(encoded) > MAX_STREAM:
        raise stream_error("REQUEST-BOUND")
    deadline = min(controller.deadline, time.monotonic() + timeout_seconds)
    if controller.cancelled.is_set() or time.monotonic() >= deadline:
        raise stream_error("CANCELLED" if controller.cancelled.is_set() else "TIMEOUT")
    process = subprocess.Popen(
        [sys.executable, "-m", "subllm.stream_worker"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, env=_worker_environment(policy_file), start_new_session=True,
    )
    text, usage, finish, tools = "", {}, "", False
    controller.worker = process
    try:
        _write_request(process, encoded, controller, deadline)
        total, buffer = 0, bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            ended = False
            while not ended:
                if scope is not None:
                    scope.remaining()
                if controller.cancelled.is_set():
                    raise stream_error("CANCELLED")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise stream_error("TIMEOUT")
                if not selector.select(min(0.05, remaining)):
                    continue
                chunk = os.read(process.stdout.fileno(), 8192)
                total += len(chunk)
                if not chunk:
                    raise stream_error("TRUNCATED")
                if total > MAX_STREAM * 3:
                    raise stream_error("RESPONSE-BOUND")
                buffer.extend(chunk)
                if len(buffer) > MAX_EVENT * 2 and b"\n" not in buffer:
                    raise stream_error("EVENT-BOUND")
                while b"\n" in buffer:
                    line, _, rest = buffer.partition(b"\n")
                    buffer = bytearray(rest)
                    if len(line) > MAX_EVENT * 2:
                        raise stream_error("EVENT-BOUND")
                    frame = decode_response_json(line)
                    if (not isinstance(frame, dict)
                            or set(frame) != {"kind", "text", "data", "native_id", "native_type"}
                            or any(not isinstance(value, str) for value in frame.values())):
                        raise stream_error("INVALID-EVENT")
                    kind = frame["kind"]
                    if kind in {"result", "error"}:
                        result = decode_response_json(frame["data"].encode())
                        part = result.get("partial", {}) if kind == "error" else result
                        usage, finish = part.get("usage", {}), part.get("finish_reason", "")
                        tools = part.get("tools", False)
                        if not isinstance(usage, dict) or not isinstance(finish, str) or type(tools) is not bool:
                            raise stream_error("INVALID-TERMINAL")
                        if kind == "error":
                            if result.get("retryable") is True and not controller.observed:
                                raise _RetryableAttemptError("provider stream unavailable",
                                    outcome=result.get("outcome", "transport_error"),
                                    provider_level=result.get("provider_level") is True)
                            raise stream_error("PROVIDER-ERROR")
                        ended = True
                        break
                    if kind not in {"provider_event", "text_delta", "tool_call_delta", "usage"}:
                        raise stream_error("INVALID-EVENT")
                    controller.observed = True
                    if kind == "text_delta":
                        text += frame["text"]
                        if len(text.encode()) > MAX_OUTPUT:
                            raise stream_error("OUTPUT-BOUND")
                    if kind == "tool_call_delta":
                        tools = True
                    if kind == "usage":
                        counters = decode_response_json(frame["data"].encode())
                        if counters.get("final") is True:
                            usage = counters["usage"]
                    controller.emit(kind, text=frame["text"], data=frame["data"],
                                    native_id=frame["native_id"], native_type=frame["native_type"])
                    # Only provider-final counters settle a debit on disconnect.
        status = wait_exit(process, deadline, scope.remaining if scope is not None else lambda: None)
        if status != 0 or controller.cancelled.is_set():
            raise stream_error("CANCELLED" if controller.cancelled.is_set() else "WORKER-FAILED")
        return CompletionResponse(text, route.provider, route.wire_model, usage, finish,
                                  raw={"stream": True, "tool_calls_present": tools})
    except BaseException as error:
        if not isinstance(error, CompletionError):
            error = stream_error("WORKER-FAILED")
        error.partial_response = CompletionResponse(text, route.provider, route.wire_model, usage, finish,
                                                   raw={"stream": True, "incomplete": True,
                                                        "tool_calls_present": tools})
        raise error from None
    finally:
        stop_group(process)
        process.stdout.close()
        if not process.stdin.closed:
            process.stdin.close()
        controller.worker = None
