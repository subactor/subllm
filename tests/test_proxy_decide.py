"""Pins for the pure System One helpers extracted from proxy.py (SUB-08 step 1)."""

from __future__ import annotations

import pytest

from subllm import proxy, proxy_decide, proxy_forward, proxy_security
from subllm.proxy_decide import (
    _build_ollama_d1_questions,
    _build_system_one_messages,
    _extract_json_object,
    _model_family,
    _normalize_ollama_d1_response,
    _normalize_system_one_probabilities,
)

QUESTIONS = [
    {"id": "route", "type": "choice", "options": ["local", "cloud", "skip"]},
    {"id": "safe", "type": "noul"},
    {"id": "effort", "type": "score", "options": ["1", "2", "3"]},
]


def test_proxy_keeps_reexporting_moved_names():
    for module in (proxy_decide, proxy_forward, proxy_security):
        public = [name for name in vars(module) if not name.startswith("__") and callable(getattr(module, name))]
        for name in public:
            if getattr(module, name).__module__ == module.__name__ and hasattr(proxy, name):
                assert getattr(proxy, name) is getattr(module, name)
    assert proxy._normalize_ollama_d1_response is _normalize_ollama_d1_response
    assert proxy.ProxyUnauthorizedError is proxy_security.ProxyUnauthorizedError
    assert proxy.forward_usage_counts is proxy_forward.forward_usage_counts


def test_explicit_probabilities_are_normalized_and_summarized():
    probabilities, answers = _normalize_system_one_probabilities(QUESTIONS, {
        "probabilities": {
            "route": {"local": 2, "cloud": 1, "skip": "nan"},
            "safe": {"true": 0.3, "false": 0.1},
            "effort": {"1": 0, "2": 1, "3": 1},
        },
    })
    assert probabilities["route"] == {"local": pytest.approx(0.666667), "cloud": pytest.approx(0.333333), "skip": 0.0}
    assert answers == {"route": "local", "safe": True, "effort": 2.5}


def test_named_answers_give_peaked_and_unmatched_give_uniform_distributions():
    probabilities, answers = _normalize_system_one_probabilities(QUESTIONS, {
        "answers": {"route": "CLOUD", "safe": False},
        "effort": "nope",
    })
    assert probabilities["route"] == {"local": 0.08, "cloud": 0.84, "skip": 0.08}
    assert probabilities["safe"] == {"true": 0.16, "false": 0.84}
    assert probabilities["effort"] == {"1": 0.333333, "2": 0.333333, "3": 0.333333}
    assert answers["route"] == "cloud" and answers["safe"] is False


def test_bool_keyed_probabilities_and_top_level_question_maps():
    probabilities, _ = _normalize_system_one_probabilities(
        [{"id": "safe", "type": "noul"}], {"safe": {True: 3, False: 1}},
    )
    assert probabilities["safe"] == {"true": 0.75, "false": 0.25}


def test_questions_without_id_or_options_are_skipped():
    probabilities, answers = _normalize_system_one_probabilities(
        [{"id": "", "type": "choice"}, {"id": "x", "type": "choice", "options": []}], {},
    )
    assert probabilities == {} and answers == {}


def test_extract_json_object_tolerates_fences_and_prose():
    assert _extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json_object('answer: {"b": 2} done') == {"b": 2}
    assert _extract_json_object("[1, 2]") == {}
    assert _extract_json_object("no json") == {}


def test_system_one_messages_skip_malformed_questions():
    messages = _build_system_one_messages({"state": {"k": 1}, "questions": [QUESTIONS[0], "bad", {"id": " "}]})
    assert [m["role"] for m in messages] == ["system", "user"]
    assert '"questions": [{"id": "route"' in messages[1]["content"]
    assert messages[1]["content"].count('"id"') == 1


def test_d1_round_trip_for_all_question_types():
    payload = {"questions": QUESTIONS}
    converted = _build_ollama_d1_questions(payload)
    assert converted["route"]["criteria"] == {"local": "local", "cloud": "cloud", "skip": "skip"}
    assert converted["safe"]["criteria"]["true"] == "The statement is true."
    assert converted["effort"]["criteria"] == ["1", "2", "3"]
    result = _normalize_ollama_d1_response({"answers": {
        "route": {"choice": "local", "probabilities": {"local": 0.7, "cloud": 0.2, "skip": 0.1}},
        "safe": {"noul": 0.25},
        "effort": {"score": 2, "probabilities": {"0": 0.1, "1": 0.6, "2": 0.3}},
    }}, payload)
    assert result["answers"] == {"route": "local", "safe": False, "effort": 2}
    assert result["probabilities"]["safe"] == {"true": 0.25, "false": 0.75}
    assert result["probabilities"]["effort"] == {"1": 0.1, "2": 0.6, "3": 0.3}


@pytest.mark.parametrize(("questions", "message"), [
    ("nope", "questions array"),
    ([], "at least one valid question"),
    ([{"id": "a", "type": "choice", "options": []}], "has no options"),
    ([{"id": "a", "type": "score", "options": ["1"]}], "between 2 and 10"),
    ([{"id": "a", "type": "vote"}], "unsupported"),
    ([{"id": "a", "type": "noul"}, {"id": "a", "type": "noul"}], "duplicate"),
])
def test_d1_question_errors(questions, message):
    with pytest.raises(ValueError, match=message):
        _build_ollama_d1_questions({"questions": questions})


@pytest.mark.parametrize(("answer", "message"), [
    ({}, "answer for 'route' is missing"),
    ({"route": {"choice": "other", "probabilities": {}}}, "choice answer"),
    ({"route": {"choice": "local", "probabilities": {"local": 0, "cloud": 0, "skip": 0}}}, "are empty"),
    ({"route": {"choice": "local", "probabilities": {"local": 1.5}}}, r"outside \[0, 1\]"),
    ({"route": {"choice": "local", "probabilities": {"local": True}}}, "not numeric"),
])
def test_d1_response_errors(answer, message):
    with pytest.raises(ValueError, match=message):
        _normalize_ollama_d1_response({"answers": answer}, {"questions": QUESTIONS[:1]})


def test_d1_response_rejects_unsupported_type_and_missing_answers():
    with pytest.raises(ValueError, match="answers object is missing"):
        _normalize_ollama_d1_response({}, {"questions": QUESTIONS})
    with pytest.raises(ValueError, match="unsupported"):
        _normalize_ollama_d1_response({"answers": {"v": {}}}, {"questions": [{"id": "v", "type": "vote"}]})


@pytest.mark.parametrize(("model", "family"), [
    ("ollama/glm-4.6", "glm"), ("qwen3:8b", "qwen"), ("claude-sonnet", "claude"), ("openai/gpt-5", "gpt"),
    ("Terra-1", "gpt"), ("gemini-2.5", "gemini"), ("deepseek-r1", "deepseek"), ("grok-4", "grok"),
    ("llama3.2", "llama"), ("mistral", "custom"),
])
def test_model_family(model, family):
    assert _model_family(model) == family


def test_strict_legacy_decision_rejects_fabricated_defaults_and_preserves_native_d1_source():
    from subllm.proxy_decide import StrictDecisionError, normalize_system_one_decision

    for bad in ("", "not json", "[1, 2]", "null", '{"answers":{"route":"cloud","route":"local"}}',
                '{"probabilities":{"route":{"local":NaN,"cloud":0.5,"skip":0.5}}}',
                '{"probabilities":{"route":{"local":0.5,"cloud":0.5,"skip":0.0}}}',
                '{"answers":{"route":"unknown","safe":true,"effort":"2"}}'):
        with pytest.raises(StrictDecisionError):
            normalize_system_one_decision(QUESTIONS, bad)

    label_only = normalize_system_one_decision(
        QUESTIONS,
        '{"answers":{"route":"local","safe":false,"effort":"3"}}',
    )
    assert label_only["answers"] == {"route": "local", "safe": False, "effort": 3.0}
    assert label_only["probabilities"] == {"route": None, "safe": None, "effort": None}
    assert label_only["decision_source"] == "legacy_json"
    assert label_only["probability_kind"] == "uncalibrated_label"

    d1 = _normalize_ollama_d1_response({"answers": {
        "route": {"choice": "local", "probabilities": {"local": 0.9, "cloud": 0.05, "skip": 0.05}},
        "safe": {"noul": 0.8},
        "effort": {"score": 1.0, "probabilities": {"0": 0.2, "1": 0.6, "2": 0.2}},
    }}, {"questions": QUESTIONS})
    assert d1["decision_source"] == "native_d1"
    assert d1["probability_kind"] == "native_calibrated"
