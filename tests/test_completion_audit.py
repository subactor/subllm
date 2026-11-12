from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import FrozenInstanceError, asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_http_transport_bounds import serve

from subllm import CompletionResponse, client_routes, complete, interaction_store, resolve, usage
from subllm.client_types import _RetryableAttemptError
from subllm.interaction_context import ACTIVE_ARCHIVE
from subllm.interaction_store import InteractionStore


@pytest.fixture
def captured(monkeypatch, tmp_path):
    store = InteractionStore(directory=tmp_path / "archive")
    monkeypatch.setattr(interaction_store, "get_default_interaction_store", lambda: store)
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(Path(__file__).resolve().parents[1] / "subllm.toml"))
    token = ACTIVE_ARCHIVE.set(None)
    route = resolve("onedev-agent", "code-edit", provider="zai", environ={
        "SUBLLM_PROVIDER_ORDER": "zai", "ZAI_API_KEY": "test.audit-fixture",
    })
    calls = []
    monkeypatch.setattr(client_routes, "available_routes", lambda *a, **kw: [route])
    monkeypatch.setattr(client_routes, "order_with_last_resort", lambda routes, **kw: routes)

    def invoke(route, messages, **kwargs):
        calls.append(route.wire_model)
        return CompletionResponse("test-private-response", route.provider, route.wire_model,
                                  {"prompt_tokens": 3, "completion_tokens": 2}, "stop")

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    yield SimpleNamespace(store=store, route=route, calls=calls, invoke=invoke)
    ACTIVE_ARCHIVE.reset(token)


def call(request_id="audit-request", content="test-private-prompt", **kwargs):
    return complete("onedev-agent", "code-edit", [{"role": "user", "content": content}],
                    request_id=request_id, environ={}, **kwargs)


def journal_row(reference):
    with closing(sqlite3.connect(usage.journal_path())) as db:
        db.row_factory = sqlite3.Row
        return dict(db.execute("SELECT * FROM attempts WHERE id=?", (int(reference.id),)).fetchone())


def test_receipt_is_immutable_and_readable_without_disclosing_payloads(captured, tmp_path):
    response = call()
    audit = response.audit
    attempt, = audit.attempts
    assert audit.request_id == audit.correlation_id == "audit-request"
    assert audit.state == attempt.state == attempt.archive_state == attempt.journal_state == "stored"
    row = journal_row(attempt.journal)
    assert row["request_id"] == attempt.journal.request_id_hash == hashlib.sha256(b"audit-request").hexdigest()[:24]
    assert row["archive_id"] == attempt.archive.id and row["archive_day"] == attempt.archive.day
    saved = captured.store.get_interaction(attempt.archive.id, attempt.archive.day)
    assert saved["correlation_id"] == attempt.archive.correlation_id == audit.correlation_id
    assert saved["status"] == "success" and saved["response"]["content"] == response.content
    assert usage.query_interaction_detail(attempt.journal.id)["id"] == attempt.archive.id
    assert len(captured.calls) == 1
    encoded = json.dumps(asdict(audit))
    for private in ("test-private-response", "test-private-prompt", "test.audit-fixture", str(tmp_path)):
        assert private not in encoded
    with pytest.raises(FrozenInstanceError):
        audit.state = "disabled"
    with pytest.raises(FrozenInstanceError):
        attempt.journal.id = "0"
    assert CompletionResponse("legacy", "provider", "model").audit is None


@pytest.mark.parametrize("phase", ["begin", "finish", "default-store"])
def test_archive_failure_preserves_one_result_and_only_journal_receipt(captured, monkeypatch, phase):
    def unavailable(*args, **kwargs):
        raise OSError("test-private-storage-error")

    target = interaction_store if phase == "default-store" else captured.store
    monkeypatch.setattr(target, "get_default_interaction_store" if phase == "default-store" else phase, unavailable)
    result = call()
    attempt, = result.audit.attempts
    assert result.content == "test-private-response" and len(captured.calls) == 1
    assert result.audit.state == attempt.archive_state == "unavailable"
    assert attempt.archive is None and attempt.journal_state == "stored"
    assert journal_row(attempt.journal)["archive_id"] is None


def test_archive_disabled_is_distinct_from_failure_and_does_not_reuse_a_reference(captured, monkeypatch):
    first = call("first-request")
    monkeypatch.setattr(interaction_store, "get_default_interaction_store", lambda: None)
    second = call("second-request")
    attempt, = second.audit.attempts
    assert first.audit.attempts[0].archive is not None
    assert attempt.archive_state == "disabled" and attempt.archive is None
    assert attempt.journal_state == second.audit.state == "stored"
    assert journal_row(attempt.journal)["request_id"] != first.audit.attempts[0].journal.request_id_hash


def test_failed_journal_commit_never_returns_an_allocated_row_id(captured, monkeypatch):
    original = sqlite3.connect

    class RollbackOnCommit(sqlite3.Connection):
        def __exit__(self, *args):
            self.rollback()
            raise sqlite3.OperationalError("test-only commit refusal")

    def connect(path, *args, **kwargs):
        if str(path) == str(usage.journal_path()):
            kwargs["factory"] = RollbackOnCommit
        return original(path, *args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connect)
    result = call()
    attempt, = result.audit.attempts
    assert len(captured.calls) == 1 and result.content == "test-private-response"
    assert result.audit.state == attempt.journal_state == "unavailable" and attempt.journal is None
    assert attempt.archive_state == "stored" and attempt.archive is not None
    with closing(original(usage.journal_path())) as db:
        assert not db.execute("SELECT name FROM sqlite_master WHERE name='attempts'").fetchall()


@pytest.mark.parametrize("acknowledge", ["absent", "pending", "forged"])
def test_pending_or_forged_archive_finish_never_claims_stored(captured, monkeypatch, acknowledge):
    original = captured.store.finish

    def finish(record, *args, **kwargs):
        if acknowledge == "absent":
            return None
        if acknowledge == "pending":
            return record
        return {**original(record, *args, **kwargs), "id": "0" * 32}

    monkeypatch.setattr(captured.store, "finish", finish)
    result = call()
    attempt, = result.audit.attempts
    assert len(captured.calls) == 1 and result.content == "test-private-response"
    assert attempt.archive_state == "unavailable" and attempt.archive is None
    assert journal_row(attempt.journal)["archive_id"] is None


def test_deleted_pending_archive_row_cannot_be_acknowledged(captured, monkeypatch):
    original = captured.store.begin

    def begin(**kwargs):
        record = original(**kwargs)
        with captured.store.connect(record["day"], True) as db:
            captured.store.sql(db, "DELETE FROM interactions WHERE day=? AND id=?", (record["day"], record["id"]))
        return record

    monkeypatch.setattr(captured.store, "begin", begin)
    result = call()
    attempt, = result.audit.attempts
    assert len(captured.calls) == 1 and result.content == "test-private-response"
    assert attempt.archive_state == "unavailable" and attempt.archive is None
    assert journal_row(attempt.journal)["archive_id"] is None


def test_two_fallbacks_keep_all_actual_committed_references(captured, monkeypatch):
    routes = [replace(captured.route, wire_model=f"test-model-{index}") for index in range(3)]
    monkeypatch.setattr(client_routes, "available_routes", lambda *args, **kwargs: routes)

    def invoke(route, messages, **kwargs):
        captured.calls.append(route.wire_model)
        if route != routes[-1]:
            raise _RetryableAttemptError("test-only model failure", outcome="model_unavailable", provider_level=False)
        return CompletionResponse("accepted", route.provider, route.wire_model)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    result = call("fallback-request")
    assert len(captured.calls) == len(result.attempts) == len(result.audit.attempts) == 3
    assert [attempt.status for attempt in result.audit.attempts] == ["error", "error", "success"]
    assert result.audit.state == "stored"
    assert len({attempt.archive.id for attempt in result.audit.attempts}) == 3
    assert len({attempt.journal.id for attempt in result.audit.attempts}) == 3
    for attempt in result.audit.attempts:
        saved = captured.store.get_interaction(attempt.archive.id, attempt.archive.day)
        assert saved["correlation_id"] == result.audit.correlation_id == "fallback-request"
        assert journal_row(attempt.journal)["archive_id"] == attempt.archive.id


@pytest.mark.parametrize("same_request_id", [False, True])
def test_nested_completions_restore_the_outer_audit_context(captured, monkeypatch, same_request_id):
    nested = []

    def invoke(route, messages, **kwargs):
        if messages[0]["content"] == "outer":
            nested.append(call("outer-request" if same_request_id else "inner-request", "inner"))
        return captured.invoke(route, messages, **kwargs)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    outer = call("outer-request", "outer")
    inner, = nested
    assert len(captured.calls) == 2
    assert len(outer.audit.attempts) == len(inner.audit.attempts) == 1
    assert outer.audit.state == inner.audit.state == "stored"
    assert outer.audit.attempts[0].archive.id != inner.audit.attempts[0].archive.id
    assert outer.audit.attempts[0].journal.id != inner.audit.attempts[0].journal.id
    for result in (outer, inner):
        attempt, = result.audit.attempts
        saved = captured.store.get_interaction(attempt.archive.id, attempt.archive.day)
        assert saved["correlation_id"] == result.audit.request_id
        assert journal_row(attempt.journal)["archive_id"] == attempt.archive.id


def test_concurrent_requests_never_cross_references(captured, monkeypatch):
    barrier = threading.Barrier(4, timeout=10)

    def invoke(route, messages, **kwargs):
        barrier.wait()
        return captured.invoke(route, messages, **kwargs)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(call, [f"parallel-{index}" for index in range(8)]))
    assert len(captured.calls) == 8
    assert len({result.audit.attempts[0].archive.id for result in results}) == 8
    assert len({result.audit.attempts[0].journal.id for result in results}) == 8
    for result in results:
        assert result.audit.state == "stored"
        attempt, = result.audit.attempts
        saved = captured.store.get_interaction(attempt.archive.id, attempt.archive.day)
        assert saved["correlation_id"] == result.audit.request_id
        assert journal_row(attempt.journal)["request_id"] == attempt.journal.request_id_hash
        assert journal_row(attempt.journal)["archive_id"] == attempt.archive.id


def test_gateway_parent_correlation_is_preserved_without_a_false_journal_link(captured):
    parent = captured.store.begin(kind="llm", caller="gateway-caller", target="route", request={})
    token = ACTIVE_ARCHIVE.set((captured.store, parent))
    try:
        result = call("gateway-child-request")
    finally:
        ACTIVE_ARCHIVE.reset(token)
    attempt, = result.audit.attempts
    assert result.audit.state == "stored"
    assert result.audit.correlation_id == attempt.archive.correlation_id == parent["id"]
    assert result.audit.request_id == "gateway-child-request"
    assert journal_row(attempt.journal)["archive_id"] is None
    saved = captured.store.get_interaction(attempt.archive.id, attempt.archive.day)
    assert saved["caller"] == "gateway-caller" and saved["correlation_id"] == parent["id"]


@pytest.mark.parametrize("archive_failed,journal_failed", [(False, False), (True, False), (False, True), (True, True)])
def test_real_worker_http_and_storage_failures_never_repeat_inference(
    monkeypatch, tmp_path, archive_failed, journal_failed,
):
    monkeypatch.setenv("SUBLLM_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setattr(interaction_store, "_DEFAULT_STORE", None)
    if archive_failed:
        def unavailable(*args, **kwargs):
            raise OSError("test-only archive finish refusal")
        monkeypatch.setattr(InteractionStore, "finish", unavailable)
    if journal_failed:
        blocked = tmp_path / "blocked-journal"
        blocked.mkdir()
        monkeypatch.setenv("SUBLLM_USAGE_DB", str(blocked))
    payload = json.dumps({"choices": [{"message": {"content": "loopback-result"}, "finish_reason": "stop"}],
                          "usage": {"prompt_tokens": 3, "completion_tokens": 2}}).encode()
    with serve(payload=payload) as (base, requests):
        policy = (Path(__file__).resolve().parents[1] / "subllm.toml").read_text()
        policy = policy.replace("enabled = true", "enabled = false")
        policy += (f'\n[custom_providers.audit_fixture]\napi_base = "{base}/v1"\n'
                   'default_model = "fixture-model"\npriority = 1\nenabled = true\n'
                   'routes = ["onedev-agent/code-edit"]\n')
        policy_file = tmp_path / "subllm.toml"
        policy_file.write_text(policy)
        monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy_file))
        result = complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}],
                          request_id="real-audit-fixture", timeout_seconds=10, cwd=tmp_path)
    assert requests == ["POST"] and result.content == "loopback-result"
    assert result.usage == {"prompt_tokens": 3, "completion_tokens": 2}
    attempt, = result.audit.attempts
    assert (attempt.archive is None) == archive_failed
    assert (attempt.journal is None) == journal_failed
    assert result.audit.state == ("unavailable" if archive_failed or journal_failed else "stored")
    if not archive_failed:
        store = interaction_store.get_default_interaction_store()
        assert store.get_interaction(attempt.archive.id, attempt.archive.day)["response"]["content"] == result.content
    if not journal_failed:
        assert journal_row(attempt.journal)["request_id"] == attempt.journal.request_id_hash
