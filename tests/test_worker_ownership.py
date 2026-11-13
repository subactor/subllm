"""Real process death and bounded cancellation; only loopback synthetic inference."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from test_request_scope import http_provider
from test_streaming import policy

from subllm import CompletionError, RequestAuditContext, complete, request_scope
from subllm.worker_lifetime import owned_communicate, worker_environment

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux ownership capability")


def living(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[0] not in {"Z", "X"}
    except (FileNotFoundError, ProcessLookupError):
        return False


def stopped(pid, seconds=5):
    deadline = time.monotonic() + seconds
    while living(pid) and time.monotonic() < deadline:
        time.sleep(0.02)
    return not living(pid)


PARENT = '''
import json,sys,time,subprocess
from pathlib import Path
from subllm import RequestAuditContext,complete,stream_complete,request_scope
original=subprocess.Popen
def spawn(*a,**kw):
    child=original(*a,**kw)
    Path(sys.argv[1]).write_text(str(child.pid))
    return child
subprocess.Popen=spawn
with request_scope(timeout_seconds=30,audit=RequestAuditContext(None,sys.argv[1]+".sqlite3")):
    function=stream_complete if sys.argv[2]=="stream" else complete
    result=function("onedev-agent","code-edit",[{"role":"user","content":"fixture"}])
    if sys.argv[2]=="stream":result.result()
'''


@pytest.mark.parametrize("mode", ["complete", "stream"])
@pytest.mark.parametrize("termination", [signal.SIGTERM, signal.SIGKILL])
def test_parent_death_stops_native_worker(monkeypatch, tmp_path, mode, termination):
    with http_provider(blocked=True) as (base, requests, started, release):
        policy(monkeypatch, tmp_path, base)
        marker = tmp_path / "owned-worker.pid"
        parent = subprocess.Popen([sys.executable, "-c", PARENT, str(marker), mode],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        worker = None
        try:
            assert started.wait(15), "real worker must reach loopback HTTP before parent death"
            worker = int(marker.read_text())
            assert living(worker)
            parent.send_signal(termination)
            parent.wait(timeout=5)
            assert stopped(worker), "owned inference survived its parent"
            assert len(requests) == 1
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait()
            if worker is not None and living(worker):
                os.killpg(worker, signal.SIGKILL)
            release.set()


@pytest.mark.parametrize("inherit_stdout", [False, True])
def test_normal_leader_exit_stops_its_still_living_descendant(tmp_path, inherit_stdout):
    marker = tmp_path / "descendant.pid"
    source = ('import subprocess,sys\nfrom pathlib import Path\n'
              'from subllm.worker_lifetime import install_owner_guard\ninstall_owner_guard()\n'
              'child=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"],'
              f'stdout={"None" if inherit_stdout else "subprocess.DEVNULL"})\n'
              f'Path({str(marker)!r}).write_text(str(child.pid))\n'
              'print("result",flush=True)\n')
    process = subprocess.Popen([sys.executable, "-c", source], start_new_session=True,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               env=worker_environment())
    child = None
    try:
        output, _ = owned_communicate(process, b"", 5)
        child = int(marker.read_text())
        assert process.returncode == 0 and output == b"result\n"
        assert stopped(child)
    finally:
        if child is not None and living(child):
            os.kill(child, signal.SIGKILL)


@pytest.mark.parametrize("reason", ["cancel", "deadline"])
def test_request_lifetime_is_shorter_than_attempt_timeout(monkeypatch, tmp_path, reason):
    import subllm.client_workers as workers
    import subllm.worker_lifetime as lifetime
    original, spawned = workers.subprocess.Popen, []
    stop = lifetime.stop_group
    stopped_at, cancelled_at = [], []

    def observe_stop(process):
        stop(process)
        stopped_at.append(time.monotonic())

    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        spawned.append(child)
        return child

    monkeypatch.setattr(workers.subprocess, "Popen", spawn)
    monkeypatch.setattr(lifetime, "stop_group", observe_stop)
    with http_provider(blocked=True) as (base, requests, started, release):
        policy(monkeypatch, tmp_path, base)
        with request_scope(timeout_seconds=5 if reason == "cancel" else 2,
                           audit=RequestAuditContext(None, tmp_path / "lifetime.sqlite3"),
                           environ={"SUBLLM_ATTEMPT_TIMEOUT_SECONDS": "30",
                                    "SUBLLM_SLOW_RESPONSE_SECONDS": "1"}) as scope:
            def cancel():
                if started.wait(10):
                    cancelled_at.append(time.monotonic())
                    scope.cancel()

            canceller = threading.Thread(target=cancel, daemon=True) if reason == "cancel" else None
            if canceller:
                canceller.start()
            before = time.monotonic()
            with pytest.raises(CompletionError):
                complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}], timeout_seconds=30)
            assert time.monotonic() - before < 20  # Audit finalization is outside the inference deadline.
            assert all(child.returncode is not None for child in spawned)
            effect_limit = cancelled_at[0] if reason == "cancel" else scope.deadline
            assert stopped_at and max(stopped_at) - effect_limit < 3
            if canceller:
                canceller.join(2)
            release.set()
    assert len(requests) <= 1 and spawned
