"""Owned native worker pipes and Linux parent-thread death supervision.

Uses Linux PR_SET_PDEATHSIG and waitid(WNOWAIT), as in the local autonom
publisher ownership design. The group leader stays unreaped until killpg,
preventing PID reuse between observing exit and stopping descendants.
"""
from __future__ import annotations

import ctypes
import os
import selectors
import signal
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from threading import get_native_id

from .errors import CompletionError

OWNER_ENV = "SUBLLM_WORKER_OWNER_PID"


def worker_environment(environment=None):
    env = dict(os.environ if environment is None else environment)
    # Every native worker must load the same installed/candidate source as its
    # parent, including Cursor when an inherited PYTHONPATH names an old release.
    source = str(Path(__file__).resolve().parents[1])
    other = [p for p in env.get("PYTHONPATH", "").split(os.pathsep) if p and p != source]
    env["PYTHONPATH"] = os.pathsep.join([source, *other])
    if sys.platform == "linux":
        env.update({OWNER_ENV: str(os.getpid()), "SUBLLM_WORKER_OWNER_TID": str(get_native_id())})
    from .request_scope import current_scope
    scope = current_scope()
    if scope is not None:
        from .request_scope import catalog_digest
        env["SUBLLM_WORKER_POLICY_SHA256"] = scope.snapshot.policy.source_sha256
        env["SUBLLM_WORKER_CATALOG_SHA256"] = catalog_digest()
        if scope.snapshot.policy.source is not None:
            env["SUBLLM_POLICY_FILE"] = str(scope.snapshot.policy.source)
    return env


def install_owner_guard():
    expected = os.environ.get(OWNER_ENV)
    if expected is None:
        return  # Direct legacy worker calls still enforce their native policy.
    if sys.platform != "linux" or not expected.isdecimal():
        raise CompletionError("worker parent-death supervision unavailable")

    def owner_gone(*_args):
        os.killpg(os.getpgrp(), signal.SIGKILL)

    if os.getpgrp() != os.getpid():
        raise CompletionError("worker requires an isolated process group")
    signal.signal(signal.SIGUSR2, owner_gone)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = (ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong)
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(1, signal.SIGUSR2, 0, 0, 0) != 0:
        raise CompletionError("worker parent-death supervision unavailable")
    thread = os.environ.get("SUBLLM_WORKER_OWNER_TID", expected)
    if (not thread.isdecimal() or os.getppid() != int(expected)
            or not Path(f"/proc/{expected}/task/{thread}").is_dir()):
        owner_gone()


def stop_group(process):
    if process.returncode is not None:
        return
    if os.name != "posix":  # pragma: no cover
        process.kill()
        process.wait()
        return
    with suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
        time.sleep(0.02)
        os.killpg(process.pid, signal.SIGKILL)
    with suppress(subprocess.TimeoutExpired):
        process.wait(timeout=1.0)
    if process.returncode is None:
        process.wait()


def wait_exit(process, deadline, check=lambda: None):
    if process.returncode is not None:
        return process.returncode
    if not hasattr(os, "WNOWAIT"):  # pragma: no cover
        return process.wait(timeout=max(0.001, deadline - time.monotonic()))
    while True:
        check()
        observed = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if observed is not None:
            return observed.si_status if observed.si_code == os.CLD_EXITED else -observed.si_status
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(process.args, 0)
        time.sleep(0.01)


def owned_communicate(process, encoded, timeout_seconds, *, maximum=2_000_000):
    from .request_scope import current_scope

    scope = current_scope()
    deadline = time.monotonic() + timeout_seconds
    if scope is not None:
        deadline = min(deadline, scope.deadline)
    if not hasattr(process, "stdin") or os.name != "posix":  # Legacy test adapters / non-POSIX compatibility.
        return process.communicate(input=encoded, timeout=timeout_seconds)
    output, offset = bytearray(), 0
    try:
        with selectors.DefaultSelector() as selector:
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "input")
            selector.register(process.stdout, selectors.EVENT_READ, "output")
            while selector.get_map():
                if scope is not None:
                    scope.remaining()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(process.args, timeout_seconds)
                for key, _mask in selector.select(min(0.05, remaining)):
                    if key.data == "input":
                        try:
                            offset += os.write(key.fd, encoded[offset:offset + 8192])
                        except BrokenPipeError:
                            offset = len(encoded)
                        if offset == len(encoded):
                            selector.unregister(key.fileobj)
                            process.stdin.close()
                    else:
                        chunk = os.read(key.fd, 8192)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        output.extend(chunk)
                        if len(output) > maximum:
                            raise CompletionError("worker result exceeds bounded output")
                if process.returncode is None and hasattr(os, "WNOWAIT"):
                    exited = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
                    if exited is not None:
                        stop_group(process)
            wait_exit(process, deadline, scope.remaining if scope is not None else lambda: None)
        return bytes(output), None
    finally:
        stop_group(process)
        for stream in (process.stdin, process.stdout):
            if not stream.closed:
                stream.close()


def verify_worker_policy():
    expected = os.environ.get("SUBLLM_WORKER_POLICY_SHA256")
    if expected is not None:
        from .policy_config import load_policy_config
        if load_policy_config().source_sha256 != expected:
            raise CompletionError("worker resolved policy digest mismatch")
        from .request_scope import catalog_digest
        if os.environ.get("SUBLLM_WORKER_CATALOG_SHA256") != catalog_digest():
            raise CompletionError("worker resolved catalog digest mismatch")
