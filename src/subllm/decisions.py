"""Offline typed decisions through Ollama's native System One API.

``decide`` accepts native named questions; ``decide_legacy`` adapts SubLLM's
question array for existing libraries. Both use a literal loopback HTTP origin,
ignore proxy environment variables, reject redirects and never invoke a chat
model or a provider fallback. Set SUBLLM_DECISION_BASE_URL for a dedicated local
daemon. Model concentration is advisory, not authorization or correctness.
"""

from __future__ import annotations

import ipaddress
import json
import math
import os
import time
import uuid
from collections.abc import Mapping
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .client_types import CompletionResponse
from .interaction_context import begin_attempt, finish_attempt
from .usage import identifier, record_attempt

_MAX_REQUEST = 262144
_MAX_RESPONSE = 1048576


class DecisionError(RuntimeError):
    """A local inference failure; no alternate inference has been attempted."""

    def __init__(self, message, *, outcome="invalid_response", private_exchange=None):
        super().__init__(message)
        self.outcome = outcome
        self.private_exchange = private_exchange or {}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise DecisionError("Offline decision redirects are forbidden", outcome="transport_error")


def _local_url(base_url):
    try:
        url = urlsplit(base_url)
        host, port = url.hostname, url.port
        if (url.scheme != "http" or url.username is not None or url.password is not None
                or url.path not in ("", "/") or url.query or url.fragment or port == 0):
            raise ValueError
        host = "127.0.0.1" if host == "localhost" else host
        if not ipaddress.ip_address(host).is_loopback:
            raise ValueError
        authority = f"[{host}]" if ":" in host else host
        return f"http://{authority}" + (f":{port}" if port is not None else "") + "/v1/systemone"
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Decision endpoint must be a literal loopback HTTP origin") from None


def _number(value, *, maximum=1.0):
    if type(value) not in (int, float) or not 0 <= value <= maximum or not math.isfinite(value):
        raise DecisionError("Invalid native decision number")
    return float(value)


def _text(value, maximum=8192):
    return isinstance(value, str) and 0 < len(value) <= maximum


def _validate_questions(questions):
    if not isinstance(questions, Mapping) or not 1 <= len(questions) <= 64:
        raise ValueError("Decision questions must contain between1 and64 named questions")
    for key, question in questions.items():
        if (not _text(key, 128) or not isinstance(question, Mapping)
                or set(question) - {"type", "instructions", "criteria"}
                or not _text(question.get("instructions"))):
            raise ValueError("Invalid native decision question")
        kind, criteria = question.get("type"), question.get("criteria")
        if kind == "choice":
            valid = isinstance(criteria, Mapping) and 2 <= len(criteria) <= 255
        elif kind == "noul":
            valid = criteria is None or isinstance(criteria, Mapping) and set(criteria) == {"true", "false"}
        elif kind == "score":
            valid = (isinstance(criteria, list) and 2 <= len(criteria) <= 10
                     and all(_text(v) for v in criteria))
        else:
            valid = False
        if isinstance(criteria, Mapping):
            valid = valid and all(_text(k, 4096) and (v is None or _text(v)) for k, v in criteria.items())
        if not valid:
            raise ValueError("Invalid criteria for native decision question")


def _distribution(value, options):
    if not isinstance(value, Mapping) or set(value) != set(options):
        raise DecisionError("Native decision probability options differ")
    probabilities = {key: _number(probability) for key, probability in value.items()}
    if abs(sum(probabilities.values()) - 1.0) > 0.001:
        raise DecisionError("Native decision probabilities do not sum to1")
    return probabilities


def _validate_response(data, questions, model):
    if not isinstance(data, dict) or data.get("model") != model:
        raise DecisionError("Native decision model identity differs")
    usage = data.get("usage")
    if (not isinstance(usage, Mapping) or type(usage.get("input_tokens")) is not int
            or not 0 <= usage["input_tokens"] <= 10**12
            or type(usage.get("output_tokens")) is not int or usage["output_tokens"] != 0):
        raise DecisionError("Native decision usage must report input tokens and zero output tokens")
    answers = data.get("answers")
    if not isinstance(answers, Mapping) or set(answers) != set(questions):
        raise DecisionError("Native decision answers differ from the questions")
    for key, question in questions.items():
        answer, kind = answers[key], question["type"]
        if not isinstance(answer, Mapping) or answer.get("type") != kind:
            raise DecisionError("Native decision answer type differs")
        if kind == "noul":
            _number(answer.get("noul"))
            continue
        options = question["criteria"] if kind == "choice" else [str(i) for i in range(len(question["criteria"]))]
        probabilities = _distribution(answer.get("probabilities"), options)
        if "confidence" in answer:
            _number(answer["confidence"])
        if kind == "choice":
            chosen = answer.get("choice")
            if (not isinstance(chosen, str) or chosen not in probabilities
                    or probabilities[chosen] < max(probabilities.values()) - 0.000001):
                raise DecisionError("Native choice is outside the catalog or contradicts its probabilities")
        else:
            score = _number(answer.get("score"), maximum=len(options) - 1)
            if abs(score - sum(int(k) * v for k, v in probabilities.items())) > 0.001:
                raise DecisionError("Native score contradicts its probability distribution")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate native JSON key")
        result[key] = value
    return result


def _post(url, body, timeout):
    request = Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(_MAX_RESPONSE + 1)
        if len(raw) > _MAX_RESPONSE:
            raise DecisionError("Native decision response exceeds its size bound")
        return json.loads(raw, object_pairs_hook=_unique_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))
    except HTTPError as error:
        with error:
            exchange = {"status": error.code, "body": error.read(8192).decode("utf-8", "replace")}
        raise DecisionError("Local decision inference returned an HTTP error", outcome=f"http_{error.code}",
                            private_exchange=exchange) from None
    except (TimeoutError, URLError, OSError) as error:
        timeout_error = isinstance(error, TimeoutError) or isinstance(getattr(error, "reason", None), TimeoutError)
        outcome = "timeout" if timeout_error else "transport_error"
        raise DecisionError("Local decision inference unavailable", outcome=outcome) from None
    except (ValueError, UnicodeError):
        raise DecisionError("Invalid native decision JSON") from None


def decide(state, questions, *, model=None, base_url=None, timeout_seconds=120.0,
           keep_alive=90, application="subllm", function="decision-routing", request_id=None):
    """Return validated native answers; failures raise without alternate inference.

    The default120second socket timeout includes cold loading; a bounded90second
    keep-alive amortizes subsequent calls. Neither value is a latency guarantee.
    Request/response capture uses the existing private archive and usage journal.
    """
    model = model or os.environ.get("SUBLLM_DECISION_MODEL") or "d1:3b"
    model = "d1:3b" if model == "d1" else model
    if model != "d1:3b":
        raise ValueError("Offline decisions require the actual local d1:3b model")
    url = _local_url(base_url or os.environ.get("SUBLLM_DECISION_BASE_URL") or "http://127.0.0.1:11434")
    if (type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 300
            or not math.isfinite(timeout_seconds) or type(keep_alive) is not int or not 0 <= keep_alive <= 300):
        raise ValueError("Invalid bounded decision timeout or keep-alive")
    if not isinstance(state, (str, dict, list)):
        raise ValueError("Decision state must be text, a JSON object or an array")
    _validate_questions(questions)
    request_id = request_id or uuid.uuid4().hex
    if any(not isinstance(value, str) or identifier(value) != value for value in (request_id, application, function)):
        raise ValueError("Invalid decision usage identity")
    payload = {"model": model, "state": state, "questions": questions, "keep_alive": keep_alive}
    body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
    if len(body) > _MAX_REQUEST:
        raise ValueError("Native decision request exceeds its size bound")
    route = SimpleNamespace(application=application, function=function, provider="ollama", wire_model=model,
                            model_parameters={})
    entry = begin_attempt(route, [], None, request_id=request_id, timeout_seconds=timeout_seconds,
                          native_request=payload)
    started, response, error = time.monotonic(), None, None
    try:
        data = _post(url, body, timeout_seconds)
        _validate_response(data, questions, model)
        response = CompletionResponse(json.dumps(data), "ollama", model, data["usage"], raw=data)
        return data
    except Exception as caught:
        error = caught
        raise
    finally:
        duration_ms = round((time.monotonic() - started) * 1000)
        finish_attempt(entry, route, response, error, duration_ms)
        record_attempt(request_id=request_id, application=application, function=function,
                       provider="ollama", model=model,
                       status="error" if error else "success",
                       diagnostic_code="SUBLLM-PROVIDER-UNAVAILABLE" if error else None,
                       duration_ms=duration_ms, usage=response.usage if response else {})


def decide_legacy(payload, *, application="subllm", function="decision-routing", **kwargs):
    """Adapt existing typed question arrays, preserving caller score labels."""
    from .proxy import _build_ollama_d1_questions, _normalize_ollama_d1_response

    if (not isinstance(payload, Mapping) or not isinstance(payload.get("questions"), list)
            or not payload["questions"]
            or any(not isinstance(q, Mapping) or not _text(q.get("id"), 128)
                   or q.get("type") not in ("choice", "noul", "score") for q in payload["questions"])):
        raise ValueError("Legacy decisions require valid named typed questions")
    data = decide(payload.get("state", {}), _build_ollama_d1_questions(payload),
                  model=payload.get("model") or None, application=application, function=function, **kwargs)
    parsed = _normalize_ollama_d1_response(data, payload)
    # The native score uses zero-based levels; consumers can use other numeric
    # labels. Their probabilities bind to those exact labels, not native indices.
    for question in payload["questions"]:
        if question["type"] == "score":
            key = question["id"]
            try:
                labels = {k: float(k) for k in parsed["probabilities"][key]}
                if not all(math.isfinite(value) for value in labels.values()):
                    raise ValueError("Nonfinite score labels")
                parsed["answers"][key] = sum(labels[k] * v for k, v in parsed["probabilities"][key].items())
            except ValueError:
                parsed["answers"][key] = data["answers"][key]["score"]
    return {**parsed, "model": data["model"], "provider": "ollama", "usage": data["usage"]}
