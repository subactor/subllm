from __future__ import annotations

import asyncio
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from subllm import client_routes, interaction_store
from subllm.client_types import CompletionResponse, _RetryableAttemptError
from subllm.interaction_context import ACTIVE_ARCHIVE, begin_attempt, finish_attempt
from subllm.interaction_store import InteractionStore
from subllm.usage import journal_path, query_interaction_detail, query_usage, record_attempt


@pytest.fixture
def captured_sdk(monkeypatch, tmp_path):
    store = InteractionStore(directory=tmp_path / "private-archive",
                             postgres_dsn=os.environ.get("SUBLLM_TEST_POSTGRES_DSN"))
    monkeypatch.setattr(interaction_store, "get_default_interaction_store", lambda: store)
    archive_context = ACTIVE_ARCHIVE.set(None)
    finish_attempt(None, None, None, None, 0)
    route = SimpleNamespace(application="onedev-agent", function="code-edit", provider="zai",
                            wire_model="glm-5.3", model_parameters={})
    yield store, route
    finish_attempt(None, None, None, None, 0)
    ACTIVE_ARCHIVE.reset(archive_context)


def reply(text="PRIVATE REPLY"):
    return CompletionResponse(text, "zai", "glm-5.3", {"prompt_tokens": 12, "completion_tokens": 4}, "stop")


def call(route, text="PRIVATE PROMPT", request_id="same-request"):
    return client_routes._complete_route(route, [{"role": "user", "content": text}], timeout_seconds=5,
                                         request_id=request_id, response_format=None, cwd=journal_path().parent)


def log(route, request_id="same-request", **changes):
    values = dict(request_id=request_id, application=route.application, function=route.function,
                  provider=route.provider, model=route.wire_model, status="success", diagnostic_code=None,
                  duration_ms=1, usage={"prompt_tokens": 12, "completion_tokens": 4})
    return record_attempt(**(values | changes))


def detail(row):
    return query_interaction_detail(str(row["id"]))


def rows():
    return query_usage({"limit": 50})["attempts"]


def pending(route, marker="PRIVATE PROMPT"):
    entry = begin_attempt(route, [{"role": "user", "content": marker}], None, request_id="same-request")
    finish_attempt(entry, route, reply(marker), None, 1)
    return entry


def test_sdk_success_links_exact_private_record_and_keeps_journal_payload_free(captured_sdk, monkeypatch):
    _, route = captured_sdk
    calls = []

    def invoke(*args, **kwargs):
        calls.append(1)
        return reply()

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    assert call(route).content == "PRIVATE REPLY"
    found = rows()
    saved = detail(found[0])
    assert len(calls) == len(found) == 1
    assert saved["payload_capture"]["state"] == "stored"
    assert saved["request"]["messages"][0]["content"] == "PRIVATE PROMPT"
    assert saved["response"]["content"] == "PRIVATE REPLY"
    assert saved["usage_attempt_id"] == found[0]["id"]
    assert not {"request", "response", "archive_ref"} & found[0].keys()
    assert b"PRIVATE PROMPT" not in journal_path().read_bytes()
    assert b"PRIVATE REPLY" not in journal_path().read_bytes()


@pytest.mark.parametrize("input_tokens", [0, 12])
def test_native_decision_captures_exact_wire_body_and_preserves_zero_usage(captured_sdk, monkeypatch, input_tokens):
    from subllm.decisions import decide

    calls = []
    native = {"model": "d1:3b", "usage": {"input_tokens": input_tokens, "output_tokens": 0},
              "answers": {"allowed": {"type": "noul", "noul": 0.05}}}

    def post(url, body, timeout):
        calls.append(json.loads(body))
        return native

    monkeypatch.setattr("subllm.decisions._post", post)
    assert decide({"query": "PRIVATE NATIVE STATE"},
                  {"allowed": {"type": "noul", "instructions": "PRIVATE NATIVE QUESTION"}},
                  application="willmux", function="decision-routing", request_id="native-capture") == native
    found = rows()
    assert len(calls) == len(found) == 1
    saved = detail(found[0])
    assert saved["payload_capture"]["state"] == "stored"
    assert saved["request"] == calls[0]
    assert "messages" not in saved["request"]
    assert saved["response"]["raw"] == native
    assert saved["response"]["finish_reason"] == ""
    assert saved["metadata"]["input_tokens"] == found[0]["input_tokens"] == input_tokens
    assert saved["metadata"]["output_tokens"] == found[0]["output_tokens"] == 0
    assert b"PRIVATE NATIVE" not in journal_path().read_bytes()


@pytest.mark.parametrize("failure", ["begin", "finish"])
def test_native_capture_failure_never_repeats_inference_or_claims_payload(captured_sdk, monkeypatch, failure):
    from subllm.decisions import decide

    store, _ = captured_sdk
    calls = []

    def post(*args):
        calls.append(1)
        return {"model": "d1:3b", "usage": {"input_tokens": 12, "output_tokens": 0},
                "answers": {"allowed": {"type": "noul", "noul": 0.05}}}

    def broken(*args, **kwargs):
        raise OSError("PRIVATE NATIVE STORAGE ERROR")

    monkeypatch.setattr("subllm.decisions._post", post)
    monkeypatch.setattr(store, failure, broken)
    decide("PRIVATE NATIVE STATE", {"allowed": {"type": "noul", "instructions": "May it run?"}})
    assert calls == [1]
    assert len(rows()) == 1
    assert detail(rows()[0])["payload_capture"]["state"] == "unlinked"


def test_sdk_error_links_original_attempt_and_does_not_repeat_provider(captured_sdk, monkeypatch):
    _, route = captured_sdk
    calls = []
    error = _RetryableAttemptError("PRIVATE ERROR", outcome="http_429")

    def invoke(*args, **kwargs):
        calls.append(1)
        raise error

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    with pytest.raises(_RetryableAttemptError) as caught:
        call(route)
    assert caught.value is error and len(calls) == 1
    saved = detail(rows()[0])
    assert saved["payload_capture"]["state"] == "stored"
    assert saved["diagnostic"]["httpStatus"] == 429
    assert saved["response"]["outcome"] == "http_429"
    assert b"PRIVATE ERROR" not in journal_path().read_bytes()


def test_router_failover_records_distinct_exact_provider_attempts(captured_sdk, monkeypatch):
    from subllm.client import complete

    calls = []

    def invoke(route, messages, **kwargs):
        calls.append(route.provider)
        if route.provider == "zai":
            raise _RetryableAttemptError("TEST_ONLY capacity failure", outcome="http_429", provider_level=True)
        return CompletionResponse("fallback result", route.provider, route.wire_model)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    result = complete("onedev-agent", "code-edit", [{"role": "user", "content": "PRIVATE PROMPT"}],
                      request_id="shared-correlation", environ={
                          "SUBLLM_PROVIDER_ORDER": "zai,openrouter", "ZAI_API_KEY": "test.id",
                          "OPENROUTER_API_KEY": "test-key",
                      })
    assert result.content == "fallback result" and calls == ["zai", "openrouter"]
    found = rows()
    saved = [detail(row) for row in found]
    assert len(saved) == len({v["id"] for v in saved}) == 2
    assert {v["status"] for v in found} == {"success", "error"}
    assert all(v["metadata"]["provider"] == row["provider"] for v, row in zip(saved, found, strict=True))


def test_nested_sdk_calls_with_same_correlation_keep_distinct_exact_references(captured_sdk, monkeypatch):
    _, route = captured_sdk

    def invoke(_route, messages, **kwargs):
        text = messages[0]["content"]
        if text == "outer":
            assert call(route, "inner").content == "inner"
        return reply(text)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    assert call(route, "outer").content == "outer"
    saved = [detail(row) for row in rows()]
    assert len({v["id"] for v in saved}) == 2
    assert {v["response"]["content"] for v in saved} == {"inner", "outer"}
    assert all(v["request"]["messages"][0]["content"] == v["response"]["content"] for v in saved)


def test_parallel_sdk_calls_do_not_exchange_capture_references(captured_sdk, monkeypatch):
    _, route = captured_sdk
    barrier = threading.Barrier(8)

    def invoke(_route, messages, **kwargs):
        barrier.wait(timeout=10)
        return reply(messages[0]["content"])

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda n: call(route, str(n)), range(8)))
    assert {v.content for v in results} == set(map(str, range(8)))
    saved = [detail(row) for row in rows()]
    assert len(saved) == len({v["id"] for v in saved}) == 8
    assert all(v["request"]["messages"][0]["content"] == v["response"]["content"] for v in saved)


def test_async_contexts_keep_finished_pending_references_separate(captured_sdk):
    _, route = captured_sdk

    async def task(marker):
        pending(route, marker)
        await asyncio.sleep(0)
        assert log(route)

    async def run():
        await asyncio.gather(task("first"), task("second"))

    asyncio.run(run())
    saved = [detail(row) for row in rows()]
    assert len({v["id"] for v in saved}) == 2
    assert {v["response"]["content"] for v in saved} == {"first", "second"}


@pytest.mark.parametrize(("field", "value"), [
    ("request_id", "another-request"), ("application", "another-app"), ("function", "another-function"),
    ("provider", "openrouter"), ("model", "another-model"),
])
def test_mismatched_identity_consumes_reference_without_disclosing_payload(captured_sdk, field, value):
    _, route = captured_sdk
    pending(route)
    assert log(route, **{field: value})
    assert log(route)
    assert all(detail(row)["payload_capture"]["state"] == "unlinked" for row in rows())


def test_exact_reference_is_one_shot_and_never_looks_up_old_correlation(captured_sdk):
    _, route = captured_sdk
    entry = pending(route)
    assert len(entry) == 2  # Preserve the existing capture entry contract.
    assert "usage_identity" not in json.loads(json.dumps(entry[1]))
    assert log(route) and log(route)
    saved = [detail(row) for row in reversed(rows())]
    assert [v["payload_capture"]["state"] for v in saved] == ["stored", "unlinked"]
    assert saved[0]["id"] == entry[1]["id"]


def test_new_disabled_capture_clears_previously_finished_reference(captured_sdk, monkeypatch):
    _, route = captured_sdk
    pending(route)
    monkeypatch.setattr(interaction_store, "get_default_interaction_store", lambda: None)
    assert begin_attempt(route, [], None, request_id="same-request") is None
    assert log(route)
    assert detail(rows()[0])["payload_capture"]["state"] == "unlinked"


@pytest.mark.parametrize("failure", ["begin", "finish", "default-store", "active-begin"])
def test_capture_failure_preserves_one_success_and_fixed_diagnostics(captured_sdk, monkeypatch, caplog, failure):
    store, route = captured_sdk
    pending(route)
    calls = []

    def invoke(*args, **kwargs):
        calls.append(1)
        return reply()

    def broken(*args, **kwargs):
        raise OSError("PRIVATE STORAGE SECRET")

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    archive_context = None
    if failure == "active-begin":
        archive_context = ACTIVE_ARCHIVE.set((store, {"caller": "parent", "id": "parent-id"}))
        monkeypatch.setattr(store, "begin", broken)
    elif failure == "default-store":
        monkeypatch.setattr(interaction_store, "get_default_interaction_store", broken)
    else:
        monkeypatch.setattr(store, failure, broken)
    try:
        assert call(route).content == "PRIVATE REPLY"
    finally:
        if archive_context is not None:
            ACTIVE_ARCHIVE.reset(archive_context)
    assert len(calls) == len(rows()) == 1
    assert detail(rows()[0])["payload_capture"]["state"] == "unlinked"
    assert "PRIVATE STORAGE SECRET" not in caplog.text


def test_active_parent_capture_links_attempt_instead_of_parent(captured_sdk, monkeypatch):
    store, route = captured_sdk
    parent = store.begin(kind="llm", caller=route.application, target="route", request={})
    archive_context = ACTIVE_ARCHIVE.set((store, parent))
    monkeypatch.setattr(client_routes, "_invoke_route", lambda *a, **kw: reply())
    try:
        assert call(route, request_id=parent["id"]).content == "PRIVATE REPLY"
    finally:
        ACTIVE_ARCHIVE.reset(archive_context)
    saved = detail(rows()[0])
    assert saved["id"] != parent["id"]
    assert saved["metadata"]["parent_id"] == parent["id"]


def test_different_gateway_parent_identity_is_preserved_and_never_misattributed(captured_sdk, monkeypatch):
    store, route = captured_sdk
    parent = store.begin(kind="llm", caller="parent-app", target="route", request={})
    archive_context = ACTIVE_ARCHIVE.set((store, parent))
    monkeypatch.setattr(client_routes, "_invoke_route", lambda *a, **kw: reply())
    try:
        assert call(route).content == "PRIVATE REPLY"
    finally:
        ACTIVE_ARCHIVE.reset(archive_context)
    assert detail(rows()[0])["payload_capture"]["state"] == "unlinked"
    saved = store.query(parent["day"], kind="llm_attempt")[0]
    assert saved["caller"] == parent["caller"]
    assert saved["correlation_id"] == parent["id"]
    assert saved["metadata"]["parent_id"] == parent["id"]


@pytest.mark.parametrize(("field", "value"), [
    ("id", "b" * 32), ("day", "2026-02-30"), ("id", "invalid"),
])
def test_invalid_finished_identity_does_not_replace_result_or_reuse_old_reference(
    captured_sdk, monkeypatch, field, value,
):
    store, route = captured_sdk
    pending(route)
    original = store.finish

    def changed(*args, **kwargs):
        return original(*args, **kwargs) | {field: value}

    monkeypatch.setattr(store, "finish", changed)
    monkeypatch.setattr(client_routes, "_invoke_route", lambda *a, **kw: reply())
    assert call(route).content == "PRIVATE REPLY"
    assert detail(rows()[0])["payload_capture"]["state"] == "unlinked"


def test_explicit_reference_wins_and_consumes_implicit_reference(captured_sdk):
    store, route = captured_sdk
    first = pending(route)
    second = store.begin(kind="llm_attempt", caller=route.application, target=route.wire_model,
                         request={}, correlation_id="same-request")
    second = store.finish(second, {"content": "explicit"}, metadata={
        "application": route.application, "function": route.function, "provider": route.provider,
        "model": route.wire_model,
    })
    assert first[1]["id"] != second["id"]
    assert log(route, archive_ref={"id": second["id"], "day": second["day"]})
    assert log(route)
    saved = [detail(row) for row in reversed(rows())]
    assert saved[0]["id"] == second["id"]
    assert saved[1]["payload_capture"]["state"] == "unlinked"


def test_invalid_explicit_reference_never_falls_back_to_pending_capture(captured_sdk):
    _, route = captured_sdk
    pending(route)
    assert not log(route, archive_ref={"id": "invalid", "day": "2026-10-28"})
    assert log(route)
    assert detail(rows()[0])["payload_capture"]["state"] == "unlinked"


def test_journal_failure_preserves_completion_and_consumes_reference(captured_sdk, monkeypatch):
    _, route = captured_sdk
    calls = []

    def invoke(*args, **kwargs):
        calls.append(1)
        return reply()

    def broken(*args, **kwargs):
        raise OSError("PRIVATE DATABASE SECRET")

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    with monkeypatch.context() as m:
        # Capture completes first. Only journal path resolution is faulted.
        import subllm.usage

        m.setattr(subllm.usage, "journal_path", broken)
        assert call(route).content == "PRIVATE REPLY"
    assert len(calls) == 1
    assert log(route)
    assert detail(rows()[0])["payload_capture"]["state"] == "unlinked"
