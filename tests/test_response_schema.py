"""Caller schemas are local contracts; rejected paid answers use native failover."""
import io
import json
import os
import sqlite3
import sys

import pytest

from subllm import CompletionError, client_routes, complete
from subllm.client_cli import completion_main
from subllm.client_types import CompletionResponse
from subllm.errors import RESPONSE_QUALITY_CODE
from subllm.quality_schema import schema_gate

ENV = {"ZAI_API_KEY": "id.secret", "SUBLLM_PROVIDER_ORDER": "zai"}
MESSAGES = [{"role": "user", "content": "Assess the ticket."}]
SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"state": {"enum": ["healthy", "degraded"]},
                   "confidence": {"type": "number", "minimum": 0, "maximum": 1}},
    "required": ["state", "confidence"],
}
GOOD = '{"state":"healthy","confidence":0.9}'


def install_answers(monkeypatch, answers):
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append((route.wire_model, kwargs.get("response_format")))
        return CompletionResponse(answers[len(calls) - 1], route.provider, route.wire_model,
                                  usage={"prompt_tokens": 40, "completion_tokens": 10})

    monkeypatch.setattr(client_routes, "_invoke_route", invoke)
    return calls


@pytest.mark.parametrize("bad", [
    '{"state":"unknown","confidence":0.9}', '{"state":"healthy","confidence":2}',
    '{"state":"healthy"}', '{"state":"healthy","confidence":0.9,"secret":true}',
    '{"state":"healthy","confidence":true}', '[]', 'not JSON',
    '{"state":"degraded","state":"healthy","confidence":0.9}',
    '{"state":"healthy","confidence":NaN}',
])
def test_schema_mismatch_changes_model_and_records_paid_error(monkeypatch, bad):
    calls = install_answers(monkeypatch, [bad, GOOD])
    monkeypatch.setattr(client_routes, "record_failure", lambda *a, **kw: pytest.fail("account quarantined"))
    wire = {"type": "json_object"}
    result = complete("todo2code", "semantic", MESSAGES, environ=ENV,
                      response_format=wire, quality_schema=SCHEMA)
    assert calls == [("glm-5.3", wire), ("glm-5.3-flash", wire)]
    assert result.content == GOOD
    expected = "invalid_response" if bad in {
        'not JSON', '[]', '{"state":"healthy","confidence":NaN}',
    } else "quality_rejected"
    assert [a.outcome for a in result.attempts] == [expected, "success"]
    with sqlite3.connect(os.environ["SUBLLM_USAGE_DB"]) as db:
        rows = db.execute(
            "select status,diagnostic_code,input_tokens,output_tokens from attempts order by id",
        ).fetchall()
    assert rows == [("error", RESPONSE_QUALITY_CODE, 40, 10), ("success", None, 40, 10)]


@pytest.mark.parametrize("schema", [
    [], "not a schema", {"type": "private-invalid-type"},
    {"$schema": "https://private.invalid/schema"},
    {"$ref": "https://private.invalid/contract"}, {"$ref": "file:///private/contract"},
    {"$ref": "#/$defs/missing"}, {"$dynamicRef": "#missing"},
    {"properties": {"x": {"$ref": "https://private.invalid/nested"}}},
    {"const": float("nan")}, {"description": "x" * 65_536},
    {"properties": {1: {"type": "string"}}},
])
def test_invalid_contract_fails_before_any_paid_request(monkeypatch, schema):
    monkeypatch.setattr(client_routes, "_invoke_route", lambda *a, **kw: pytest.fail("paid request"))
    with pytest.raises(CompletionError, match="bounded self-contained") as error:
        complete("todo2code", "semantic", MESSAGES, environ=ENV, quality_schema=schema)
    assert error.value.diagnostic_code == "SUBLLM-QUALITY-VALIDATOR-ERROR"
    assert "private" not in str(error.value)


def test_recursive_and_oversized_contracts_fail_without_recursing_or_paying(monkeypatch):
    cyclic = {}
    cyclic["properties"] = cyclic
    deep = current = {}
    for _ in range(40):
        current["properties"] = {"x": {}}
        current = current["properties"]["x"]
    many = {"properties": {str(i): {} for i in range(4097)}}
    monkeypatch.setattr(client_routes, "_invoke_route", lambda *a, **kw: pytest.fail("paid request"))
    for schema in (cyclic, deep, many):
        with pytest.raises(CompletionError, match="bounded self-contained"):
            complete("todo2code", "semantic", MESSAGES, environ=ENV, quality_schema=schema)


def test_full_schema_assertions_internal_refs_and_frozen_caller_input():
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
        "$defs": {"state": {"enum": ["healthy", "degraded"]}},
        "allOf": [{"properties": {"state": {"$ref": "#/$defs/state"}}, "required": ["state"]}],
        "if": {"properties": {"state": {"const": "degraded"}}},
        "then": {"properties": {"reason": {"type": "string", "minLength": 1}}, "required": ["reason"]},
        "unevaluatedProperties": False,
    }
    accept = schema_gate(schema, None)
    schema.clear()
    def response(content):
        return CompletionResponse(json.dumps(content), "zai", "glm-5.3")
    assert accept(response({"state": "healthy"})) is True
    assert accept(response({"state": "degraded", "reason": "queue stalled"})) is True
    for bad in ({"state": "degraded"}, {"state": "broken"}, {"state": "healthy", "extra": True}):
        assert accept(response(bad)) is False


def test_reference_like_data_is_not_mistaken_for_remote_schema_dependency():
    literal = {"$ref": "https://data.invalid/not-a-schema-reference"}
    accept = schema_gate({"const": literal}, None)
    assert accept(CompletionResponse(json.dumps(literal), "zai", "glm-5.3")) is True


@pytest.mark.parametrize("schema", [True, False])
def test_boolean_contracts_retain_json_schema_semantics(schema):
    accept = schema_gate(schema, None)
    assert accept(CompletionResponse('{}', "zai", "glm-5.3")) is schema


def test_schema_and_task_predicate_both_apply_and_broken_predicate_aborts(monkeypatch):
    calls = install_answers(monkeypatch, [GOOD, GOOD])
    seen = []

    def predicate(response):
        seen.append(response)
        return len(seen) > 1

    complete("todo2code", "semantic", MESSAGES, environ=ENV, quality_schema=SCHEMA, quality_gate=predicate)
    assert len(calls) == len(seen) == 2
    calls = install_answers(monkeypatch, [GOOD])

    def broken(_response):
        raise RuntimeError("private predicate data")

    with pytest.raises(CompletionError, match="task quality validator failed"):
        complete("todo2code", "semantic", MESSAGES, environ=ENV, quality_schema=SCHEMA, quality_gate=broken)
    assert len(calls) == 1


def test_explicit_model_is_not_replaced_after_schema_failure(monkeypatch):
    calls = install_answers(monkeypatch, ['{}'])
    with pytest.raises(CompletionError):
        complete("todo2code", "semantic", MESSAGES, environ=ENV,
                 model="glm-5.3", quality_schema=SCHEMA)
    assert len(calls) == 1


def test_stdin_cli_passes_local_schema_without_changing_wire_format(monkeypatch, capsys):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    request = {"schema": "subllm.completion-request/v1", "messages": MESSAGES,
               "response_format": {"type": "json_object"}, "quality_schema": SCHEMA}
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(request).encode())))
    calls = install_answers(monkeypatch, ['{}', GOOD])
    assert completion_main(["todo2code", "semantic", "--timeout", "5"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["content"] == GOOD and output["model"] == "glm-5.3-flash"
    assert len(calls) == 2 and all(wire == {"type": "json_object"} for _, wire in calls)


def test_adaptive_completion_preserves_local_schema(monkeypatch, tmp_path):
    from subllm import adaptive
    config = {
        "classes": {"strong": ["glm-5.3", "glm-5.3-flash"]}, "aliases": {},
        "routes": {"todo2code/semantic": "strong"}, "state": str(tmp_path / "availability.sqlite"),
        "ttl": 900, "probe_timeout": 2, "sweep_budget": 0, "sweep_interval": 60,
    }
    monkeypatch.setattr(adaptive, "policy", lambda _: config)
    calls = install_answers(monkeypatch, ['{}', GOOD])
    result = complete("todo2code", "semantic", MESSAGES, environ=ENV, quality_schema=SCHEMA)
    assert result.content == GOOD and len(calls) == 2
    assert ("zai", "glm-5.3") not in adaptive._observations(config, "text")
