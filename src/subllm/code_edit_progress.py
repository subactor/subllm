"""Bound logical completion calls and expose metadata without source or credentials."""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from uuid import uuid4

from .code_context_primitives import digest, encode
from .errors import CompletionError


class CodeEditProgress:
    def __init__(self, maximum: int, timeout: float, sink: Callable[[dict], None] | None = None):
        if type(maximum) is not int or not 1 <= maximum <= 128:
            raise CompletionError('code edit context query budget must be 1 to 128')
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            raise CompletionError('code edit timeout must be finite and positive')
        self.maximum = maximum
        self.timeout = timeout
        self.sink = sink
        self.sink_failed = False
        self.started = time.monotonic()
        self.run_id = uuid4().hex
        self.context_calls = 0
        self.edit_calls = 0
        self.sequence = 0
        self.attempts: list[dict] = []

    def emit(self, phase: str, status: str, attempt: dict | None = None) -> None:
        self.sequence += 1
        event = {
            'schema': 'subllm.code-edit-progress/v1', 'run_id': self.run_id,
            'sequence': self.sequence, 'phase': phase, 'status': status,
            'elapsed_ms': round((time.monotonic() - self.started) * 1000),
            'remaining_ms': max(0, round((self.timeout - (time.monotonic() - self.started)) * 1000)),
            'context_calls': self.context_calls, 'max_context_queries': self.maximum,
            'edit_calls': self.edit_calls,
        }
        if attempt:
            event.update({k: attempt[k] for k in ('query_id', 'function', 'record_count')})
        if self.sink is not None:
            try:
                self.sink(event)
            except Exception:
                # Observability failure never repeats or authorizes a paid completion.
                self.sink_failed = True
                self.sink = None

    def begin(self, function: str, payload: dict, response_attempt: int) -> dict:
        if self.timeout - (time.monotonic() - self.started) <= 0:
            raise CompletionError('code2dsl editing deadline exceeded')
        if function == 'code-context':
            if self.context_calls >= self.maximum:
                raise CompletionError('code edit context query budget exhausted',
                                      diagnostic_code='SUBLLM-CODE-CONTEXT-BUDGET')
            self.context_calls += 1
        elif function == 'code-edit':
            if self.edit_calls >= 2:
                raise CompletionError('code edit response attempt budget exhausted')
            self.edit_calls += 1
        else:
            raise CompletionError('code edit completion function is invalid')
        body = encode(payload).encode()
        attempt = {'query_id': f'{self.run_id}:{len(self.attempts) + 1}', 'function': function,
                   'input_bytes': len(body), 'input_sha256': digest(body),
                   'record_count': len(payload.get('records', [])),
                   'response_attempt': response_attempt, 'status': 'started'}
        self.attempts.append(attempt)
        self.emit('query', 'started', attempt)
        return attempt

    def summary(self) -> dict:
        return {'schema': 'subllm.code-edit-attempts/v1', 'run_id': self.run_id,
                'max_context_queries': self.maximum, 'context_calls': self.context_calls,
                'edit_calls': self.edit_calls, 'sink_failed': self.sink_failed}

    def receipt(self) -> dict:
        return {**self.summary(), 'queries': [dict(attempt) for attempt in self.attempts]}
