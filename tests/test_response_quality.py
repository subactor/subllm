"""Quality rejection is a paid, model-scoped attempt; task predicates own semantics."""
import json
import os
import sqlite3

import pytest

from subllm import CompletionError, client_routes, complete
from subllm.client_types import CompletionResponse, _RetryableAttemptError
from subllm.errors import RESPONSE_QUALITY_CODE
from subllm.quality import validate_response

ENV = {"ZAI_API_KEY": "id.secret", "SUBLLM_PROVIDER_ORDER": "zai"}
MESSAGES = [{"role": "user", "content": "Select the authentication task from T1 login repair and T2 logo."}]


@pytest.mark.parametrize(("content", "finish", "fmt"), (
    ("", "stop", None), ("  \n", "stop", None),
    ('{"ids":["T1"]}', "length", {"type": "json_object"}),
    ("not JSON", "stop", {"type": "json_object"}),
    ("[]", "stop", {"type": "json_object"}),
    ('{"score":NaN}', "stop", {"type": "json_object"}),
))
def test_invalid_answer_is_rejected_before_success(content, finish, fmt):
    with pytest.raises(_RetryableAttemptError) as raised:
        validate_response(CompletionResponse(content, "zai", "glm-5.3", finish_reason=finish), fmt)
    assert raised.value.provider_level is False
    assert raised.value.diagnostic_code == RESPONSE_QUALITY_CODE
    assert content not in str(raised.value) if content.strip() else True


@pytest.mark.parametrize("accepted", (False, None, 1, "yes"))
def test_task_validator_requires_explicit_acceptance(accepted):
    with pytest.raises(_RetryableAttemptError, match="task_acceptance"):
        validate_response(CompletionResponse("valid syntax, wrong task", "zai", "glm-5.3"), None,
                          lambda _: accepted)


def test_semantically_wrong_answer_changes_model_and_keeps_paid_usage(monkeypatch):
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append(route.wire_model)
        ids = ["T2"] if len(calls) == 1 else ["T1"]
        return CompletionResponse(json.dumps({"ids": ids}), route.provider, route.wire_model,
                                  usage={"prompt_tokens": 40, "completion_tokens": 10}, finish_reason="stop")

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    monkeypatch.setattr(client_routes, "record_failure", lambda *a, **kw: pytest.fail("account was penalized"))
    result = complete("todo2code", "semantic", MESSAGES, environ=ENV,
                      response_format={"type": "json_object"},
                      quality_gate=lambda r: json.loads(r.content).get("ids") == ["T1"])
    assert calls == ["glm-5.3", "glm-5.3-flash"]
    assert json.loads(result.content) == {"ids": ["T1"]}
    assert [a.outcome for a in result.attempts] == ["quality_rejected", "success"]
    assert result.attempts[0].diagnostic_code == RESPONSE_QUALITY_CODE
    with sqlite3.connect(os.environ["SUBLLM_USAGE_DB"]) as db:
        rows = db.execute(
            "select model,status,diagnostic_code,input_tokens,output_tokens from attempts order by id",
        ).fetchall()
    assert rows == [("glm-5.3", "error", RESPONSE_QUALITY_CODE, 40, 10),
                    ("glm-5.3-flash", "success", None, 40, 10)]


def test_invalid_json_changes_model_without_an_optional_predicate(monkeypatch):
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append(route.wire_model)
        return CompletionResponse("broken" if len(calls) == 1 else '{"ok":true}', route.provider, route.wire_model)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    result = complete("todo2code", "semantic", MESSAGES, environ=ENV, response_format={"type": "json_object"})
    assert result.model == "glm-5.3-flash" and len(calls) == 2


def test_validator_exception_is_not_misclassified_as_model_degradation(monkeypatch):
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append(route.wire_model)
        return CompletionResponse("answer", route.provider, route.wire_model)

    def broken(_):
        raise ValueError("private reference data must not leak")

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    with pytest.raises(CompletionError, match="task quality validator failed") as raised:
        complete("todo2code", "semantic", MESSAGES, environ=ENV, quality_gate=broken)
    assert calls == ["glm-5.3"]
    assert "private" not in str(raised.value)


def test_explicit_model_cannot_be_silently_replaced_after_quality_failure(monkeypatch):
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append(route.wire_model)
        return CompletionResponse("wrong", route.provider, route.wire_model)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    with pytest.raises(CompletionError):
        complete("todo2code", "semantic", MESSAGES, environ=ENV, model="glm-5.3-flash", quality_gate=lambda _: False)
    assert calls == ["glm-5.3-flash"]


def test_invalid_predicate_is_rejected_before_any_paid_request(monkeypatch):
    monkeypatch.setattr(client_routes, "_invoke_route", lambda *a, **kw: pytest.fail("paid request"))
    with pytest.raises(CompletionError, match="must be callable"):
        complete("todo2code", "semantic", MESSAGES, environ=ENV, quality_gate="approve")


def test_adaptive_completion_keeps_the_task_gate(monkeypatch, tmp_path):
    from subllm import adaptive
    config = {
        "classes": {"strong": ["glm-5.3", "glm-5.3-flash"]}, "aliases": {},
        "routes": {"todo2code/semantic": "strong"}, "state": str(tmp_path / "availability.sqlite"),
        "ttl": 900, "probe_timeout": 2, "sweep_budget": 0, "sweep_interval": 60,
    }
    monkeypatch.setattr(adaptive, "policy", lambda _: config)
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append(route.wire_model)
        return CompletionResponse("wrong" if len(calls) == 1 else "expected", route.provider, route.wire_model)

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    result = complete("todo2code", "semantic", MESSAGES, environ=ENV, quality_gate=lambda r: r.content == "expected")
    assert calls == ["glm-5.3", "glm-5.3-flash"]
    assert result.content == "expected"
    assert ("zai", "glm-5.3") not in adaptive._observations(config, "text")
