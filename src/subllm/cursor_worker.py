from __future__ import annotations

import ctypes
import json
import os
import signal
import sys
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .errors import CompletionError

MAX_CURSOR_WORKER_REQUEST_BYTES = 4_000_000
_PR_SET_CHILD_SUBREAPER = 36
_GRACEFUL_REAP_SECONDS = 0.25
_FORCED_REAP_SECONDS = 0.5


def _enable_child_subreaper() -> None:
    """Keep orphaned SDK descendants owned by this isolated worker on Linux."""
    if sys.platform != "linux":
        return
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        prctl = libc.prctl
        prctl.argtypes = (
            ctypes.c_int,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
            ctypes.c_ulong,
        )
        prctl.restype = ctypes.c_int
        result = prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0)
    except (AttributeError, OSError) as exc:
        raise CompletionError("Cursor worker could not enable child reaping") from exc
    if result != 0:
        raise CompletionError("Cursor worker could not enable child reaping")


def _reap_exited_children() -> bool:
    """Reap exited direct/adopted children and report whether any remain."""
    while True:
        try:
            child_pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return False
        if child_pid == 0:
            return True


def _direct_child_pids() -> tuple[int, ...]:
    try:
        encoded = Path(f"/proc/self/task/{os.getpid()}/children").read_text(
            encoding="ascii"
        )
    except OSError:
        return ()
    return tuple(int(value) for value in encoded.split())


def _terminate_and_reap_children(signum: int, _frame: Any) -> None:
    """Finish group termination without leaving daemon-owned zombie children."""
    graceful_deadline = time.monotonic() + _GRACEFUL_REAP_SECONDS
    while time.monotonic() < graceful_deadline:
        if not _reap_exited_children():
            raise SystemExit(128 + signum)
        time.sleep(0.01)

    forced_deadline = time.monotonic() + _FORCED_REAP_SECONDS
    while time.monotonic() < forced_deadline:
        for child_pid in _direct_child_pids():
            with suppress(ProcessLookupError):
                os.kill(child_pid, signal.SIGKILL)
        if not _reap_exited_children():
            raise SystemExit(128 + signum)
        time.sleep(0.01)
    raise SystemExit(128 + signum)


def _request(source: Any) -> Mapping[str, Any]:
    if not isinstance(source, Mapping) or set(source) != {
        "schema", "model", "api_key", "cwd", "name", "prompt",
    }:
        raise CompletionError("Cursor worker request must be a closed JSON object")
    if source.get("schema") != "subllm.cursor-worker-request/v1":
        raise CompletionError("Cursor worker request schema is not supported")
    for field in ("model", "api_key", "cwd", "name", "prompt"):
        value = source.get(field)
        if not isinstance(value, str) or not value or "\x00" in value:
            raise CompletionError(f"Cursor worker {field} must be a non-empty safe string")
    return source


def _usage(result: Any) -> Mapping[str, Any]:
    usage = getattr(result, "usage", None)
    if usage is None:
        return {}
    if isinstance(usage, Mapping):
        return dict(usage)
    try:
        return asdict(usage)
    except TypeError:
        return {}


def _execute(request: Mapping[str, Any]) -> Mapping[str, Any]:
    try:
        from cursor_sdk import Agent, AgentOptions, LocalAgentOptions
    except ImportError as exc:
        raise CompletionError(
            "provider cursor requires the optional dependency 'subactor-subllm[cursor]'"
        ) from exc

    option_values = {
        "model": request["model"],
        "api_key": request["api_key"],
        "local": LocalAgentOptions(cwd=request["cwd"], setting_sources=[]),
        "tools": [],
        "name": request["name"],
    }
    options = AgentOptions(**option_values)
    try:
        with Agent.create(options) as agent:
            result = agent.send(request["prompt"]).wait()
    except Exception as exc:  # noqa: BLE001 - never project SDK details or credentials
        raise CompletionError("Cursor SDK request failed") from exc
    status = str(getattr(getattr(result, "status", ""), "value", getattr(result, "status", ""))).lower()
    content = str(getattr(result, "result", "") or "")
    if status != "finished" or not content:
        raise CompletionError(f"Cursor SDK ended with status {status or 'unknown'}")
    return {
        "schema": "subllm.cursor-worker-result/v1",
        "status": "SUCCESS",
        "content": content,
        "usage": dict(_usage(result)),
        "finish_reason": "",
        "run_id": str(getattr(result, "id", "") or ""),
    }


def main() -> int:
    try:
        _enable_child_subreaper()
        if os.name == "posix":
            signal.signal(signal.SIGTERM, _terminate_and_reap_children)
        encoded = sys.stdin.buffer.read(MAX_CURSOR_WORKER_REQUEST_BYTES + 1)
        if len(encoded) > MAX_CURSOR_WORKER_REQUEST_BYTES:
            raise CompletionError("Cursor worker request exceeds 4000000 bytes")
        request = _request(json.loads(encoded.decode("utf-8")))
        result = _execute(request)
    except (UnicodeError, json.JSONDecodeError, CompletionError) as exc:
        print(f"subllm-cursor-worker: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
