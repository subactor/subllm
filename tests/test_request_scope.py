"""Pinned native request boundaries against real local HTTP and concurrent profiles."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import MappingProxyType

import pytest
from test_streaming import openai_frames, policy, provider

from subllm import (
    CompletionError,
    RequestAuditContext,
    ResolvedPolicySnapshot,
    capture_policy,
    complete,
    request_scope,
    stream_complete,
    usage,
)
from subllm.errors import InvalidPolicyError
from subllm.interaction_context import ACTIVE_ARCHIVE
from subllm.interaction_store import InteractionStore


@contextmanager
def http_provider(content="ok", *, blocked=False, on_request=None):
    requests, started, release = [], threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            if on_request is not None:
                on_request()
            started.set()
            if blocked:
                release.wait(30)
            body = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}],
                               "usage": {"prompt_tokens": 3, "completion_tokens": 2}}).encode()
            try:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests, started, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(3)


def test_snapshot_is_immutable_and_changed_source_cannot_dispatch(monkeypatch, tmp_path):
    with http_provider() as (base, requests, *_):
        policy(monkeypatch, tmp_path, base)
        snapshot = capture_policy()
        with pytest.raises(TypeError):
            ResolvedPolicySnapshot(snapshot.policy, snapshot.providers, snapshot.models, snapshot.digest)
        with pytest.raises(FrozenInstanceError):
            snapshot.digest = "changed"
        with pytest.raises(TypeError):
            snapshot.providers["changed"] = None
        with request_scope(policy=snapshot):
            routes = snapshot.resolve("onedev-agent", "code-edit")
            assert routes[0].api_base == base + "/v1"
            source = snapshot.policy.source
            source.write_text(source.read_text() + "\n# operator changed policy\n")
            with pytest.raises(InvalidPolicyError, match="source changed"):
                complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}])
    assert requests == []


def test_worker_rejects_policy_change_after_parent_dispatch_check(monkeypatch, tmp_path):
    import subllm.client_workers as workers
    original = workers._run_openai_worker

    def changed(request, **kwargs):
        source = Path(os.environ["SUBLLM_POLICY_FILE"])
        source.write_text(source.read_text() + "\n# startup race\n")
        return original(request, **kwargs)

    with http_provider() as (base, requests, *_):
        policy(monkeypatch, tmp_path, base)
        monkeypatch.setattr(workers, "_run_openai_worker", changed)
        with request_scope(), pytest.raises(CompletionError):
            complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}])
    assert requests == []


def test_late_policy_change_never_produces_a_success_from_another_snapshot(monkeypatch, tmp_path):
    source = tmp_path / "policy.toml"

    def changed():
        source.write_text(source.read_text() + "\n# changed during approved inference\n")

    with http_provider(on_request=changed) as (base, requests, *_):
        policy(monkeypatch, tmp_path, base)
        store = InteractionStore(directory=tmp_path / "archive")
        journal = tmp_path / "late-policy.sqlite3"
        with request_scope(audit=RequestAuditContext(store, journal)) as scope:
            snapshot_digest = scope.snapshot.digest
            with pytest.raises(InvalidPolicyError, match="source changed"):
                complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}])
    assert len(requests) == 1
    summary = usage.query_usage({}, database=journal)["summary"]
    assert summary["attempts"] == summary["errors"] == 1
    records = InteractionStore(directory=tmp_path / "archive").query(
        datetime.now(UTC).date().isoformat(), include_payloads=True)
    assert len(records) == 1 and records[0]["status"] == "error"
    assert records[0]["response"]["raw"]["resolved_policy_sha256"] == snapshot_digest


def test_context_catalog_drift_cannot_dispatch(monkeypatch, tmp_path):
    from subllm.policy import PROVIDERS

    with http_provider() as (base, requests, *_):
        policy(monkeypatch, tmp_path, base)
        with request_scope():
            PROVIDERS.register_custom(replace(PROVIDERS["stream_fixture"], api_base="http://127.0.0.1:1/v1"))
            with pytest.raises(InvalidPolicyError, match="catalog changed"):
                complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}])
    assert requests == []


def test_base_catalog_change_invalidates_the_captured_snapshot(monkeypatch, tmp_path):
    from subllm.policy import PROVIDERS
    with http_provider() as (base, requests, *_):
        policy(monkeypatch, tmp_path, base)
        with request_scope():
            replacement = {**PROVIDERS._base, "zai": replace(PROVIDERS._base["zai"], api_base="https://invalid.test")}
            monkeypatch.setattr(PROVIDERS, "_base", MappingProxyType(replacement))
            with pytest.raises(InvalidPolicyError, match="snapshot changed"):
                complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}])
    assert requests == []


def test_explicit_audit_context_cannot_cross_a_callers_archive(tmp_path):
    first = InteractionStore(directory=tmp_path / "first")
    second = InteractionStore(directory=tmp_path / "second")
    parent = first.begin(kind="request", caller="controller", target="fixture", request={})
    token = ACTIVE_ARCHIVE.set((first, parent))
    try:
        with pytest.raises(CompletionError, match="conflicts with caller archive"), request_scope(
                audit=RequestAuditContext(second)):
            pytest.fail("mismatched profile entered")
    finally:
        ACTIVE_ARCHIVE.reset(token)


PROFILE_CALL = '''
import json,sys
from subllm import RequestAuditContext,capture_policy,complete,request_scope,usage
from subllm.interaction_store import InteractionStore
p=json.loads(sys.argv[1])
env={"SUBLLM_POLICY_FILE":p["policy"]}
snapshot=capture_policy(environ=env)
store=InteractionStore(directory=__import__("pathlib").Path(p["archive"]))
with request_scope(policy=snapshot,environ=env,audit=RequestAuditContext(store,p["journal"])):
    response=complete("onedev-agent","code-edit",[{"role":"user","content":"fixture"}])
    print(json.dumps([response.content,response.audit.state,usage.query_usage({})["summary"]["attempts"]]))
'''


@pytest.mark.parametrize("mode", ["threads", "processes"])
def test_concurrent_profiles_keep_routes_archives_and_journals_separate(monkeypatch, tmp_path, mode):
    with http_provider("left") as (left, left_requests, *_), http_provider("right") as (right, right_requests, *_):
        profiles = []
        for index, base in enumerate((left, right)):
            folder = tmp_path / str(index)
            folder.mkdir()
            policy(monkeypatch, folder, base)
            profiles.append({"policy": str(folder / "policy.toml"), "archive": str(folder / "archive"),
                             "journal": str(folder / "journal.sqlite3")})
        barrier = threading.Barrier(2)

        def invoke(profile):
            if mode == "processes":
                result = subprocess.run([sys.executable, "-c", PROFILE_CALL, json.dumps(profile)],
                                        capture_output=True, text=True, timeout=30, check=True)
                return json.loads(result.stdout)
            environment = {"SUBLLM_POLICY_FILE": profile["policy"]}
            snapshot = capture_policy(environ=environment)
            store = InteractionStore(directory=Path(profile["archive"]))
            with request_scope(policy=snapshot, environ=environment,
                               audit=RequestAuditContext(store, profile["journal"])):
                barrier.wait(10)
                response = complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}])
                assert response.raw["resolved_policy_sha256"] == snapshot.digest
                return [response.content, response.audit.state, usage.query_usage({})["summary"]["attempts"]]

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(invoke, profiles))
    assert results == [["left", "stored", 1], ["right", "stored", 1]]
    assert len(left_requests) == len(right_requests) == 1
    for profile in profiles:
        records = InteractionStore(directory=Path(profile["archive"])).query(datetime.now(UTC).date().isoformat())
        assert records  # Actual private archive readback, not just receipt construction.


def test_stream_inherits_parent_archive_and_explicit_profile(monkeypatch, tmp_path):
    with provider(openai_frames()) as (base, requests, *_):
        policy(monkeypatch, tmp_path, base)
        store = InteractionStore(directory=tmp_path / "explicit")
        parent = store.begin(kind="request", caller="controller", target="fixture", request={})
        token = ACTIVE_ARCHIVE.set((store, parent))
        try:
            with request_scope(audit=RequestAuditContext(store, tmp_path / "explicit.sqlite3")):
                response = stream_complete("onedev-agent", "code-edit",
                                           [{"role": "user", "content": "fixture"}]).result()
                assert response.audit.correlation_id == parent["id"]
                attempt = response.audit.attempts[0]
                assert attempt.archive.correlation_id == parent["id"]
                assert store.get_interaction(attempt.archive.id, attempt.archive.day) is not None
        finally:
            ACTIVE_ARCHIVE.reset(token)
    assert len(requests) == 1


def test_cancelled_scope_cannot_start_another_call(monkeypatch, tmp_path):
    with http_provider() as (base, requests, *_):
        policy(monkeypatch, tmp_path, base)
        with request_scope() as scope:
            assert complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}]).content == "ok"
            scope.cancel()
            with pytest.raises(CompletionError, match="cancelled"):
                complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}])
    assert len(requests) == 1


def test_absolute_deadline_includes_policy_capture(monkeypatch):
    import importlib
    module = importlib.import_module("subllm.request_scope")
    original = module.capture_policy

    def slow_capture(**kwargs):
        snapshot = original(**kwargs)
        time.sleep(0.2)
        return snapshot

    monkeypatch.setattr(module, "capture_policy", slow_capture)
    with pytest.raises(CompletionError, match="deadline expired"), request_scope(timeout_seconds=0.1):
        pytest.fail("policy capture consumed the entire inference lifetime")
