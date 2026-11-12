from dataclasses import replace

import pytest
from starlette.testclient import TestClient

from subllm import client_routes
from subllm.client_types import CompletionResponse, _RetryableAttemptError
from subllm.gateway import create_app
from subllm.interaction_store import InteractionStore
from subllm.kpi_ledger import DeploymentContext, IncompleteCostMeasurementError
from subllm.kpi_usage import ACTIVE_COST, GatewayCostObserver, TokenTariff
from subllm.types import ResolvedRoute

CLIENT_CREDENTIAL = "test-cost-observer-credential-" + "a" * 32
OTHER_CREDENTIAL = "test-cost-observer-credential-" + "b" * 32
PAYLOAD = {"model": "heyasa/command", "messages": [{"role": "user", "content": "private prompt"}]}


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_COST_CLIENT_CREDENTIAL", CLIENT_CREDENTIAL)
    monkeypatch.setenv("TEST_COST_OTHER_CREDENTIAL", OTHER_CREDENTIAL)
    config = {"allowed_hosts": ["testserver"], "archive_directory": str(tmp_path / "archive"),
              "clients": {"alice": {"token_env": "TEST_COST_CLIENT_CREDENTIAL", "llm": True, "mcp": [],
                                    "compile_route": "platform/interactive"},
                          "bob": {"token_env": "TEST_COST_OTHER_CREDENTIAL", "llm": True, "mcp": []}}}
    context = DeploymentContext("deployment", "workflow", "1", "cohort", stage="evaluation", synthetic=True)
    tariff = TokenTariff("1", "2", "fixture-tariff")
    observer = GatewayCostObserver(tmp_path / "cost" / "journal.sqlite", {"alice": context, "bob": context},
                                   {("codex", "wire-first"): tariff, ("ollama", "wire-second"): tariff})
    observer.register_case("alice", "reference-a", "case-a")
    observer.register_case("bob", "reference-b", "case-b")
    first = ResolvedRoute("heyasa", "Heyasa", "https://example.test", "command", "codex", "wire-first",
                          1, "http://invalid.test", "NO_KEY", "openai/wire-first", "wire-first", {},
                          "openai-compatible", "test-key")
    second = replace(first, provider="ollama", model="wire-second", wire_model="wire-second", priority=2)
    monkeypatch.setattr(client_routes, "available_routes", lambda *a, **k: [first, second])
    monkeypatch.setattr(client_routes, "order_with_last_resort", lambda routes, **k: routes)
    return config, InteractionStore(tmp_path / "archive"), observer


def headers(credential=CLIENT_CREDENTIAL, reference="reference-a"):
    return {"Authorization": "Bearer " + credential, "X-SubLLM-Business-Case": reference}


def response(route):
    return CompletionResponse('{"matched": true}', route.provider, route.wire_model,
                              {"input_tokens": 1000, "output_tokens": 500}, "stop")


def test_real_gateway_failover_records_every_actual_attempt_and_preserves_unknown_fee(setup, monkeypatch):
    config, store, observer = setup
    calls = []

    def upstream(route, *a, **kw):
        calls.append(route.provider)
        if route.provider == "codex":
            raise _RetryableAttemptError("unavailable", outcome="provider_unavailable", provider_level=True)
        return response(route)

    monkeypatch.setattr(client_routes, "_invoke_route", upstream)
    with TestClient(create_app(config, store, cost_observer=observer)) as client:
        reply = client.post("/v1/chat/completions", headers=headers(), json=PAYLOAD)
        assert reply.status_code == 200, reply.text
        assert reply.headers["x-subllm-cost-observation"] == "recorded"
        assert reply.json()["model"] == "wire-second"
    assert calls == ["codex", "ollama"]
    events = observer.events("alice", "reference-a")
    invocations = [ev for ev in events if ev["kind"] == "model.invoked"]
    assert [(e["payload"]["model_id"], e["payload"]["fallback"]) for e in invocations] == [
        ("wire-first", False), ("wire-second", True)]
    assert all(e["case_id"] == "case-a" for e in events)
    assert not observer.summary("alice", "reference-a")["complete"]
    with pytest.raises(IncompleteCostMeasurementError):
        observer.close_case_cost("alice", "reference-a")
    assert "private prompt" not in str(observer.audit_records("alice", "reference-a"))
    assert not observer.events("bob", "reference-b")


@pytest.mark.parametrize("credential,reference,expected", [(OTHER_CREDENTIAL, "reference-a", 403),
                                                       (CLIENT_CREDENTIAL, "reference-b", 403),
                                                       (CLIENT_CREDENTIAL, "", 403), ("invalid", "reference-a", 401)])
def test_auth_and_case_grant_fail_before_any_provider(setup, monkeypatch, credential, reference, expected):
    config, store, observer = setup
    monkeypatch.setattr(client_routes, "_invoke_route", lambda *a, **kw: pytest.fail("unauthorized provider"))
    with TestClient(create_app(config, store, cost_observer=observer)) as client:
        reply = client.post("/v1/chat/completions", headers=headers(credential, reference), json=PAYLOAD)
        assert reply.status_code == expected


def test_requested_cost_measurement_requires_configured_observer(setup, monkeypatch):
    config, store, _ = setup
    monkeypatch.setattr(client_routes, "_invoke_route", lambda *a, **kw: pytest.fail("unobserved provider"))
    with TestClient(create_app(config, store)) as client:
        assert client.post("/v1/chat/completions", headers=headers(), json=PAYLOAD).status_code == 403


@pytest.mark.parametrize("failure_phase", ["admission", "observation", "finish"])
def test_journal_failure_does_not_replay_or_replace_paid_result(setup, monkeypatch, failure_phase):
    config, store, observer = setup
    calls = []
    original_db = observer._db

    def broken():
        raise OSError("private details")

    def upstream(route, *a, **kw):
        calls.append(route.provider)
        if failure_phase == "observation":
            monkeypatch.setattr(observer, "observe", broken)
        if failure_phase == "finish":
            monkeypatch.setattr(observer, "_db", broken)
        return response(route)

    monkeypatch.setattr(client_routes, "_invoke_route", upstream)
    if failure_phase == "admission":
        monkeypatch.setattr(observer, "_db", broken)
    with TestClient(create_app(config, store, cost_observer=observer)) as client:
        reply = client.post("/v1/chat/completions", headers=headers(), json=PAYLOAD)
        if failure_phase == "admission":
            assert reply.status_code == 503 and not calls
        else:
            assert reply.status_code == 200 and calls == ["codex"]
            assert reply.json()["choices"][0]["message"]["content"] == '{"matched": true}'
            assert reply.headers["x-subllm-cost-observation"] == "pending"
    monkeypatch.setattr(observer, "_db", original_db)
    assert ACTIVE_COST.get() is None
    assert not observer.summary("alice", "reference-a")["complete"]


def test_compile_and_unmeasured_requests_share_transport_without_leaking_binding(setup, monkeypatch):
    config, store, observer = setup
    monkeypatch.setattr(client_routes, "_invoke_route", lambda route, *a, **kw: response(route))
    compile_request = {"system": "Return object", "user": "matched", "schema_name": "probe",
                       "schema": {"type": "object", "required": ["matched"],
                                  "properties": {"matched": {"type": "boolean"}}}}
    with TestClient(create_app(config, store, cost_observer=observer)) as client:
        measured = client.post("/compile", headers=headers(), json=compile_request)
        assert measured.status_code == 200, measured.text
        assert measured.headers["x-subllm-cost-observation"] == "recorded"
        assert measured.json()["data"] == {"matched": True}
        unmeasured = client.post("/v1/chat/completions",
                                 headers={"Authorization": "Bearer " + CLIENT_CREDENTIAL}, json=PAYLOAD)
        assert unmeasured.status_code == 200 and "x-subllm-cost-observation" not in unmeasured.headers
    assert observer.summary("alice", "reference-a")["known_charge_count"] == 1
    assert ACTIVE_COST.get() is None
