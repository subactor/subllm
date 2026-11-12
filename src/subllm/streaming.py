"""Provisional native inference events with explicit controller feedback.

Use ``with stream_complete(...) as events`` and iterate events. Only a completed
terminal event has passed whole-response acceptance. Chunks never qualify an
atomic code patch; the caller binds checkpoints to base/spec/environment/tests.
Feedback observes or cancels this request. Restart requires a new request and
does not mutate prompts, acceptance criteria, execute tools or resume a prefix.
Metrics cover this SDK operation, not a whole Forge coding/test/deployment cycle.
"""
from __future__ import annotations

import os
import time
from collections.abc import Mapping
from contextvars import copy_context
from copy import deepcopy
from dataclasses import dataclass, replace
from queue import Empty, Full, Queue
from threading import Event, Lock, Thread
from uuid import uuid4

from .audit import capture_audit
from .client_types import CompletionResponse
from .generation import generation_scope, output_count
from .interaction_context import ACTIVE_ARCHIVE
from .native_http import normalize_timeout
from .policy_config import load_policy_config
from .stream_transport import attach_capture, stream_error, stream_scope


@dataclass(frozen=True, slots=True)
class StreamCapabilities:
    transports: tuple[str, ...] = ("openai-compatible", "anthropic", "gemini-sdk")
    feedback: str = "observe-or-cancel-and-new-request"
    cancellation: str = "local-worker-and-connection"
    executes_tools: bool = False
    resumes_prefixes: bool = False
    qualifies_code_checkpoints: bool = False


@dataclass(frozen=True, slots=True)
class StreamEvent:
    request_id: str
    epoch: int
    attempt_id: str
    sequence: int
    kind: str
    provider: str = ""
    model: str = ""
    text: str = ""
    data: str = ""
    native_id: str = ""
    native_type: str = ""
    response: CompletionResponse | None = None
    error_code: str | None = None
    provisional: bool = True


@dataclass(frozen=True, slots=True)
class StreamFeedbackReceipt:
    accepted: bool
    disposition: str
    request_id: str
    epoch: int
    sequence: int


@dataclass(frozen=True, slots=True)
class StreamMetrics:
    elapsed_seconds: float
    time_to_first_delta_seconds: float | None
    time_to_first_useful_feedback_seconds: float | None
    invalidated_output_tokens: int | None
    queue_capacity: int
    maximum_queue_size: int


class _EventQueue(Queue):
    def __init__(self, capacity):
        super().__init__(maxsize=capacity)
        self.highwater = 0

    def _put(self, item):
        super()._put(item)
        self.highwater = max(self.highwater, self._qsize())


class CompletionStream:
    capabilities = StreamCapabilities()

    def __init__(self, invoke, *, request_id, timeout_seconds, epoch=0, queue_capacity=8,
                 environ=None, generation_limits=None, generation_budget=None):
        if (not isinstance(request_id, str) or not request_id or len(request_id) > 256
                or type(epoch) is not int or not 0 <= epoch <= 2**31 - 1
                or type(queue_capacity) is not int or not 1 <= queue_capacity <= 256):
            raise stream_error("INVALID-OPTIONS")
        self.request_id, self.epoch = request_id, epoch
        self.timeout_seconds = normalize_timeout(timeout_seconds)
        self._invoke, self._environ = invoke, environ
        self._limits, self._budget = generation_limits, generation_budget
        self._queue = _EventQueue(queue_capacity)
        self._guard, self.cancelled, self._done = Lock(), Event(), Event()
        self._thread = self._terminal = None
        self._delivered_terminal = self._invalidated = False
        self._sequence, self._delivered = 0, -1
        self._started = self._finished = self._first_delta = self._first_feedback = None
        self.capture = self.generation = self.worker = None
        self._failure = None
        self.observed = False
        self.attempt_id = self.provider = self.model = ""
        self.deadline = 0.0

    def _start(self):
        with self._guard:
            if self._thread is not None:
                return
            self._started = time.monotonic()
            self.deadline = self._started + self.timeout_seconds
            context = copy_context()
            self._thread = Thread(target=context.run, args=(self._run,), daemon=True,
                                  name="subllm-inference-stream")
            self._thread.start()

    def __enter__(self):
        self._start()
        return self

    def __exit__(self, *_args):
        self.close()

    def __iter__(self):
        self._start()
        return self

    def __next__(self):
        while True:
            event = self._poll(0.05)
            if event is not None:
                return event

    def _poll(self, timeout):
        self._start()
        if self._delivered_terminal:
            raise StopIteration
        try:
            event = self._queue.get(timeout=timeout)
        except Empty:
            if not self._done.is_set():
                return None
            event = self._terminal
            self._delivered_terminal = True
        with self._guard:
            self._delivered = event.sequence
            if event.kind == "text_delta" and event.text and self._first_delta is None:
                self._first_delta = time.monotonic() - self._started
        return event

    def begin_attempt(self, route):
        self.attempt_id, self.provider, self.model = uuid4().hex, route.provider, route.wire_model
        self.emit("attempt_start")

    def emit(self, kind, **fields):
        event = StreamEvent(self.request_id, self.epoch, self.attempt_id, self._sequence,
                            kind, self.provider, self.model, **fields)
        while True:
            if self.cancelled.is_set():
                raise stream_error("CANCELLED")
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise stream_error("BACKPRESSURE-TIMEOUT")
            try:
                self._queue.put(event, timeout=min(0.05, remaining))
                self._sequence += 1
                return
            except Full:
                continue

    def _run(self):
        response = error = None
        try:
            runtime = load_policy_config(environ={**os.environ, **(self._environ or {})})
            parent = ACTIVE_ARCHIVE.get()
            correlation = parent[1]["id"] if parent is not None else self.request_id
            with (stream_scope(self), generation_scope(self._limits, self._budget, runtime.execution) as generation,
                  capture_audit(self.request_id, correlation) as capture):
                attach_capture(capture, generation)
                response = self._invoke()
        except BaseException as failure:
            error = failure
            response = getattr(failure, "partial_response", None)
        self._failure = error
        if response is None:
            response = CompletionResponse("", self.provider, self.model)
        response = replace(response, audit=self.capture.receipt() if self.capture is not None else None,
                           generation=self.generation.receipt() if self.generation is not None else None)
        with self._guard:
            if self.cancelled.is_set():
                kind, code = "cancelled", "SUBLLM-STREAM-CANCELLED"
                self._invalidated = True
            elif error is not None:
                kind, code = "error", getattr(error, "diagnostic_code", None) or "SUBLLM-STREAM-FAILED"
                self._invalidated = True
            elif response.raw.get("tool_calls_present") or response.finish_reason in {"tool_calls", "tool_use"}:
                kind, code = "tool_required", "SUBLLM-STREAM-TOOL-TURN-REQUIRED"
            else:
                kind, code = "completed", None
            self._terminal = StreamEvent(self.request_id, self.epoch, self.attempt_id, self._sequence,
                kind, response.provider, response.model, response=response, error_code=code,
                provisional=kind != "completed")
            self._finished = time.monotonic()
            self._done.set()

    @property
    def terminal(self):
        return self._terminal

    @property
    def metrics(self):
        with self._guard:
            elapsed = ((self._finished or time.monotonic()) - self._started) if self._started is not None else 0.0
            tokens = (output_count(self._terminal.response.usage)
                      if self._invalidated and self._terminal is not None else None)
            if not self._invalidated:
                tokens = 0
            return StreamMetrics(elapsed, self._first_delta, self._first_feedback, tokens,
                                 self._queue.maxsize, self._queue.highwater)

    def feedback(self, *, request_id, epoch, sequence, action="continue"):
        with self._guard:
            disposition = "observed"
            if self._done.is_set():
                disposition = "terminal"
            elif request_id != self.request_id or type(epoch) is not int or epoch != self.epoch:
                disposition = "stale_epoch_or_request"
            elif type(sequence) is not int or not 0 <= sequence <= self._delivered:
                disposition = "unknown_sequence"
            elif action not in {"continue", "cancel", "restart"}:
                disposition = "unsupported_action"
            accepted = disposition == "observed"
            if accepted:
                if self._first_feedback is None:
                    self._first_feedback = time.monotonic() - self._started
                if action != "continue":
                    self.cancelled.set()
                    self._invalidated = True
                    disposition = "restart_required" if action == "restart" else "cancel_requested"
            return StreamFeedbackReceipt(accepted, disposition, self.request_id, self.epoch, sequence)

    def cancel(self):
        with self._guard:
            if not self._done.is_set():
                self.cancelled.set()
                self._invalidated = True

    def close(self):
        self.cancel()
        if self._thread is not None:
            self._thread.join(timeout=self.timeout_seconds + 2)
            if self._thread.is_alive():
                raise stream_error("CLEANUP-PENDING")
        return self._terminal

    def result(self):
        for _event in self:
            pass
        if self._terminal.kind != "completed":
            error = stream_error("NOT-COMPLETED")
            error.diagnostic_code = self._terminal.error_code
            raise error
        return self._terminal.response


def stream_complete(application, function, messages, *, request_id=None, timeout_seconds=30,
                    epoch=0, queue_capacity=8, **kwargs):
    """Stream the existing native completion path; cache/CLI/adaptive replay is unsupported.

    Iterate inside ``with stream_complete(app, function, messages) as stream``.
    Text/tool deltas are provisional. ``stream.result()`` drains remaining
    events and returns only an accepted whole response, with native receipts.
    Use ``stream.feedback(request_id=event.request_id, epoch=event.epoch,
    sequence=event.sequence, action="cancel")`` to end local inference.
    ``action="restart"`` returns a request for an explicit new call; it never
    automatically resends a paid request or changes acceptance criteria.
    Unknown terminal usage and invalidated token cost stay unknown (None).
    """
    from .client_routes import complete

    allowed = {"response_format", "environ", "credentials", "cwd", "model", "quality_gate", "quality_schema",
               "generation_limits", "generation_budget"}
    if set(kwargs) - allowed:
        raise stream_error("UNSUPPORTED-OPTIONS")
    messages = deepcopy([dict(message) for message in messages]) if messages else messages
    kwargs = dict(kwargs)
    for key in ("response_format", "environ", "credentials", "quality_schema", "generation_limits"):
        if key in kwargs:
            value = kwargs[key]
            kwargs[key] = deepcopy(dict(value) if isinstance(value, Mapping) else value)
    identity = request_id or uuid4().hex
    return CompletionStream(
        lambda: complete(application, function, messages, request_id=identity,
                         timeout_seconds=timeout_seconds, **kwargs),
        request_id=identity, timeout_seconds=timeout_seconds, epoch=epoch, queue_capacity=queue_capacity,
        environ=kwargs.get("environ"), generation_limits=kwargs.get("generation_limits"),
        generation_budget=kwargs.get("generation_budget"),
    )
