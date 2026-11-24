"""Pure System One (decide) request/response shaping for the local proxy (extracted in SUB-08).

No I/O: question normalization, prompt construction, probability normalization and the
translation to and from Ollama's native typed d1 format. The proxy handler and
``subllm.decisions`` own the transport.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

SYSTEM_ONE_REQUEST_SCHEMA = "wellmanifest.system-one-request/v1"
SYSTEM_ONE_RESPONSE_SCHEMA = "wellmanifest.system-one-response/v1"
_MATCHED_ANSWER_PROBABILITY = 0.84
_MODEL_FAMILIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("glm", ("glm",)),
    ("qwen", ("qwen",)),
    ("claude", ("claude",)),
    ("gpt", ("gpt", "sol", "terra", "luna")),
    ("gemini", ("gemini",)),
    ("deepseek", ("deepseek",)),
    ("grok", ("grok",)),
    ("llama", ("llama",)),
)


def _normalize_question_options(raw_options: Any, q_type: str) -> tuple[list[str], dict[str, str]]:
    """Extract ordered option keys and optional human descriptions from a System One question."""
    if isinstance(raw_options, Mapping):
        keys = [str(k) for k in raw_options if str(k)]
        descriptions = {str(k): str(v) for k, v in raw_options.items() if str(k)}
        return keys, descriptions
    if isinstance(raw_options, Sequence) and not isinstance(raw_options, (str, bytes)):
        keys = [str(x) for x in raw_options if str(x)]
        return keys, {}
    if q_type == "noul":
        return ["true", "false"], {}
    if q_type == "score":
        return ["1", "2", "3"], {}
    return [], {}


def _question_identity(question: Any) -> tuple[str, str] | None:
    """``(id, type)`` of a well-formed question mapping, or None when it should be skipped."""
    if not isinstance(question, Mapping):
        return None
    q_id = str(question.get("id") or "").strip()
    if not q_id:
        return None
    return q_id, str(question.get("type") or "choice").strip().lower()


def _json_object_or_none(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    """Parse JSON object from model output, tolerating markdown fences."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    parsed = _json_object_or_none(cleaned)
    if parsed is not None:
        return parsed
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        parsed = _json_object_or_none(cleaned[start : end + 1])
        if parsed is not None:
            return parsed
    return {}


def _non_negative_probability(value: Any) -> float:
    try:
        num = float(value) if value is not None and not isinstance(value, bool) else 0.0
    except (TypeError, ValueError):
        num = 0.0
    return max(0.0, num) if math.isfinite(num) else 0.0


def _explicit_distribution(
    q_id: str,
    option_keys: Sequence[str],
    raw_probs_map: Mapping[str, Any],
    parsed_output: Mapping[str, Any],
) -> dict[str, float]:
    """Model-supplied probabilities for one question, unnormalized (empty when none were given)."""
    candidate = raw_probs_map.get(q_id)
    if not isinstance(candidate, Mapping) and isinstance(parsed_output.get(q_id), Mapping):
        candidate = parsed_output.get(q_id)
    if not isinstance(candidate, Mapping):
        return {}
    dist: dict[str, float] = {}
    for opt in option_keys:
        val = candidate.get(opt)
        if val is None and opt.lower() in ("true", "false"):
            val = candidate.get(opt.lower() == "true")
        dist[opt] = _non_negative_probability(val)
    return dist


def _chosen_option(
    q_id: str,
    option_keys: Sequence[str],
    raw_answers_map: Mapping[str, Any],
    parsed_output: Mapping[str, Any],
) -> str | None:
    """The option the model named as its answer, matched case-insensitively."""
    chosen = raw_answers_map.get(q_id)
    if chosen is None and not isinstance(parsed_output.get(q_id), Mapping):
        chosen = parsed_output.get(q_id)
    if isinstance(chosen, bool):
        chosen_str = "true" if chosen else "false"
    elif chosen is not None:
        chosen_str = str(chosen).strip()
    else:
        return None
    if not chosen_str:
        return None
    for opt in option_keys:
        if opt == chosen_str or opt.lower() == chosen_str.lower():
            return opt
    return None


def _answer_distribution(option_keys: Sequence[str], matched_opt: str | None) -> dict[str, float]:
    """Peaked distribution on the named answer, or uniform when none matched."""
    n = len(option_keys)
    if matched_opt is None:
        uni = round(1.0 / n, 6)
        return {opt: uni for opt in option_keys}
    if n == 1:
        return {matched_opt: 1.0}
    hi = _MATCHED_ANSWER_PROBABILITY
    lo = round((1.0 - hi) / (n - 1), 6)
    return {opt: (hi if opt == matched_opt else lo) for opt in option_keys}


def _summarize_answer(q_type: str, dist: Mapping[str, float]) -> Any:
    best_opt = max(dist, key=lambda k: dist[k])
    if q_type == "noul":
        return float(dist.get("true", 0.0)) >= float(dist.get("false", 0.0))
    if q_type == "score":
        try:
            return round(sum(float(k) * float(v) for k, v in dist.items()), 3)
        except ValueError:
            return best_opt
    return best_opt


def _normalize_system_one_probabilities(
    questions: Sequence[Mapping[str, Any]],
    parsed_output: Mapping[str, Any],
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Normalize raw model probabilities or chosen answers into valid probability distributions."""
    raw_probs = parsed_output.get("probabilities")
    raw_probs_map = raw_probs if isinstance(raw_probs, Mapping) else {}
    raw_answers = parsed_output.get("answers")
    raw_answers_map = raw_answers if isinstance(raw_answers, Mapping) else {}

    probabilities: dict[str, dict[str, float]] = {}
    answers: dict[str, Any] = {}
    for q in questions:
        q_id = str(q.get("id") or "").strip()
        if not q_id:
            continue
        q_type = str(q.get("type") or "choice").strip().lower()
        option_keys, _ = _normalize_question_options(q.get("options"), q_type)
        if not option_keys:
            continue
        dist = _explicit_distribution(q_id, option_keys, raw_probs_map, parsed_output)
        total = sum(dist.values())
        if total > 0:
            dist = {opt: round(v / total, 6) for opt, v in dist.items()}
        else:
            matched = _chosen_option(q_id, option_keys, raw_answers_map, parsed_output)
            dist = _answer_distribution(option_keys, matched)
        probabilities[q_id] = dist
        answers[q_id] = _summarize_answer(q_type, dist)
    return probabilities, answers


def _build_system_one_messages(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    """Build compact JSON-constrained messages for a System One decision request."""
    state = payload.get("state") if isinstance(payload.get("state"), Mapping) else {}
    raw_questions = payload.get("questions") if isinstance(payload.get("questions"), Sequence) else []
    compact_questions: list[dict[str, Any]] = []
    for q in raw_questions:
        identity = _question_identity(q)
        if identity is None:
            continue
        q_id, q_type = identity
        opt_keys, opt_descs = _normalize_question_options(q.get("options"), q_type)
        compact_questions.append({
            "id": q_id,
            "type": q_type,
            "question": str(q.get("question") or ""),
            "options": opt_descs if opt_descs else opt_keys,
        })

    system_prompt = (
        "You are a Jev / System One typed decision engine (`choice`, `score`, `noul`). "
        "Respond with ONLY a valid JSON object containing key \"answers\" mapping each question id "
        "to its single best option string from that question's options, and optional key \"probabilities\" "
        "mapping each question id to a probability distribution over its options."
    )
    user_payload = {
        "state": dict(state),
        "questions": compact_questions,
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def _d1_criteria(qid: str, qtype: str, options: Sequence[str], descriptions: Mapping[str, str]) -> Any:
    """Ollama native ``criteria`` for one typed question."""
    if qtype == "choice":
        if not options:
            raise ValueError(f"d1 choice question {qid!r} has no options")
        return {option: descriptions.get(option) or option for option in options}
    if qtype == "noul":
        return {
            "true": descriptions.get("true") or "The statement is true.",
            "false": descriptions.get("false") or "The statement is false.",
        }
    if qtype == "score":
        if not 2 <= len(options) <= 10:
            raise ValueError(f"d1 score question {qid!r} must have between 2 and 10 levels")
        return [descriptions.get(option) or option for option in options]
    raise ValueError(f"unsupported d1 System One question type: {qtype}")


def _build_ollama_d1_questions(payload: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Translate SubLLM's typed question list to Ollama's native System One format."""
    raw_questions = payload.get("questions")
    if not isinstance(raw_questions, Sequence) or isinstance(raw_questions, (str, bytes)):
        raise ValueError("typed d1 request requires a questions array")

    converted: dict[str, dict[str, Any]] = {}
    for question in raw_questions:
        identity = _question_identity(question)
        if identity is None:
            continue
        qid, qtype = identity
        options, descriptions = _normalize_question_options(question.get("options"), qtype)
        instructions = str(question.get("question") or question.get("instructions") or qid).strip() or qid
        criteria = _d1_criteria(qid, qtype, options, descriptions)
        if qid in converted:
            raise ValueError(f"duplicate d1 System One question id: {qid}")
        converted[qid] = {"type": qtype, "instructions": instructions, "criteria": criteria}

    if not converted:
        raise ValueError("typed d1 request requires at least one valid question")
    return converted


def _finite_probability(value: Any, question_id: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"malformed d1 response: probability for {question_id!r} is not numeric")
    try:
        probability = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"malformed d1 response: probability for {question_id!r} is not numeric") from exc
    if not math.isfinite(probability) or probability < 0.0 or probability > 1.0:
        raise ValueError(f"malformed d1 response: probability for {question_id!r} is outside [0, 1]")
    return probability


def _d1_choice_answer(qid: str, options: Sequence[str], answer: Mapping[str, Any]) -> tuple[Any, dict[str, float]]:
    chosen = answer.get("choice")
    raw_probs = answer.get("probabilities")
    if not isinstance(chosen, str) or chosen not in options or not isinstance(raw_probs, Mapping):
        raise ValueError(f"malformed d1 response: choice answer for {qid!r} is invalid")
    dist = {option: _finite_probability(raw_probs.get(option), qid) for option in options}
    if sum(dist.values()) <= 0:
        raise ValueError(f"malformed d1 response: choice probabilities for {qid!r} are empty")
    return chosen, dist


def _d1_noul_answer(qid: str, options: Sequence[str], answer: Mapping[str, Any]) -> tuple[Any, dict[str, float]]:
    probability = _finite_probability(answer.get("noul"), qid)
    return probability >= 0.5, {"true": probability, "false": round(1.0 - probability, 6)}


def _d1_score_answer(qid: str, options: Sequence[str], answer: Mapping[str, Any]) -> tuple[Any, dict[str, float]]:
    raw_probs = answer.get("probabilities")
    if not isinstance(raw_probs, Mapping) or not 2 <= len(options) <= 10:
        raise ValueError(f"malformed d1 response: score probabilities for {qid!r} are invalid")
    dist = {option: _finite_probability(raw_probs.get(str(index)), qid) for index, option in enumerate(options)}
    if sum(dist.values()) <= 0:
        raise ValueError(f"malformed d1 response: score probabilities for {qid!r} are empty")
    return answer.get("score"), dist


_D1_ANSWER_READERS = {"choice": _d1_choice_answer, "noul": _d1_noul_answer, "score": _d1_score_answer}


def _normalize_ollama_d1_response(
    data: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Convert Ollama's typed answers and positional score levels to SubLLM's common shape."""
    raw_answers = data.get("answers")
    if not isinstance(raw_answers, Mapping):
        raise ValueError("malformed d1 response: answers object is missing")

    normalized_answers: dict[str, Any] = {}
    normalized_probabilities: dict[str, dict[str, float]] = {}
    for question in payload.get("questions", []):
        identity = _question_identity(question)
        if identity is None:
            continue
        qid, qtype = identity
        options, _ = _normalize_question_options(question.get("options"), qtype)
        answer = raw_answers.get(qid)
        if not isinstance(answer, Mapping):
            raise ValueError(f"malformed d1 response: answer for {qid!r} is missing")
        reader = _D1_ANSWER_READERS.get(qtype)
        if reader is None:
            raise ValueError(f"unsupported d1 System One question type: {qtype}")
        normalized_answers[qid], normalized_probabilities[qid] = reader(qid, options, answer)

    return {
        "answers": normalized_answers,
        "probabilities": normalized_probabilities,
        "decision_source": "native_d1",
        "probability_kind": "native_calibrated",
    }


def _strict_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise StrictDecisionError(f"duplicate JSON key {key!r} in legacy decision response")
        result[key] = value
    return result


class StrictDecisionError(ValueError):
    """Raised when a legacy System One output violates strict contract/calibration rules."""


def _parse_strict_decision_json(raw_text: str) -> dict[str, Any]:
    """Parse strictly valid top-level JSON object without silently repairing invalid roots."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        raise StrictDecisionError("legacy decision response is empty")
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        parsed = json.loads(
            cleaned,
            object_pairs_hook=_strict_pairs,
            parse_constant=lambda c: (_ for _ in ()).throw(
                StrictDecisionError(f"nonfinite constant {c!r} in legacy decision response")
            ),
        )
    except StrictDecisionError:
        raise
    except (TypeError, ValueError) as exc:
        raise StrictDecisionError("legacy decision response is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise StrictDecisionError("legacy decision response must be a JSON object")
    return parsed


def _strict_explicit_dist(
    q_id: str,
    option_keys: Sequence[str],
    raw_probs_map: Mapping[str, Any],
    parsed_output: Mapping[str, Any],
) -> dict[str, float] | None:
    candidate = raw_probs_map.get(q_id)
    if candidate is None and isinstance(parsed_output.get(q_id), Mapping):
        candidate = parsed_output.get(q_id)
    if candidate is None:
        return None
    if not isinstance(candidate, Mapping):
        raise StrictDecisionError(f"probabilities for {q_id!r} must be a mapping")
    if set(candidate).difference(option_keys):
        raise StrictDecisionError(f"unknown probability option for {q_id!r}")
    dist: dict[str, float] = {}
    for opt in option_keys:
        val = candidate.get(opt)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not 0 <= val <= 1:
            raise StrictDecisionError(f"invalid probability for {q_id!r}/{opt!r}")
        dist[opt] = float(val)
    total = sum(dist.values())
    if total <= 0:
        raise StrictDecisionError(f"probability distribution for {q_id!r} has zero mass")
    return {opt: round(v / total, 6) for opt, v in dist.items()}


def _strict_question_result(
    q_id: str,
    q_type: str,
    option_keys: Sequence[str],
    raw_probs_map: Mapping[str, Any],
    raw_answers_map: Mapping[str, Any],
    parsed_output: Mapping[str, Any],
) -> tuple[Any, dict[str, float] | None, str]:
    dist = _strict_explicit_dist(q_id, option_keys, raw_probs_map, parsed_output)
    if dist is not None:
        ordered = sorted(dist.items(), key=lambda item: item[1], reverse=True)
        if len(ordered) >= 2 and abs(ordered[0][1] - ordered[1][1]) <= 1e-9:
            raise StrictDecisionError(f"tied probabilities for {q_id!r} require abstention")
        return _summarize_answer(q_type, dist), dist, "explicit_distribution"
    matched = _chosen_option(q_id, option_keys, raw_answers_map, parsed_output)
    if matched is None:
        raise StrictDecisionError(f"missing or unknown answer for {q_id!r}")
    if q_type == "noul":
        return matched == "true", None, "uncalibrated_label"
    if q_type == "score":
        try:
            return round(float(matched), 3), None, "uncalibrated_label"
        except ValueError:
            return matched, None, "uncalibrated_label"
    return matched, None, "uncalibrated_label"


def normalize_system_one_decision(
    questions: Sequence[Mapping[str, Any]],
    raw_text: str,
) -> dict[str, Any]:
    """Strictly parse and validate legacy System One output without fabricating probabilities."""
    parsed = _parse_strict_decision_json(raw_text)
    raw_probs = parsed.get("probabilities")
    if raw_probs is not None and not isinstance(raw_probs, Mapping):
        raise StrictDecisionError("legacy probabilities field must be an object")
    raw_answers = parsed.get("answers")
    if raw_answers is not None and not isinstance(raw_answers, Mapping):
        raise StrictDecisionError("legacy answers field must be an object")
    probs_map = raw_probs if isinstance(raw_probs, Mapping) else {}
    answers_map = raw_answers if isinstance(raw_answers, Mapping) else {}

    answers: dict[str, Any] = {}
    probabilities: dict[str, dict[str, float] | None] = {}
    probability_kinds: dict[str, str] = {}
    for question in questions:
        identity = _question_identity(question)
        if identity is None:
            raise StrictDecisionError("decision request contains invalid question")
        q_id, q_type = identity
        option_keys, _ = _normalize_question_options(question.get("options"), q_type)
        if not option_keys:
            raise StrictDecisionError(f"question {q_id!r} has no options")
        ans, dist, pkind = _strict_question_result(
            q_id, q_type, option_keys, probs_map, answers_map, parsed,
        )
        answers[q_id] = ans
        probabilities[q_id] = dist
        probability_kinds[q_id] = pkind
    if not answers:
        raise StrictDecisionError("decision request has no questions")
    kinds = probability_kinds.values()
    if all(k == "explicit_distribution" for k in kinds):
        overall_kind = "explicit_distribution"
    elif all(k == "uncalibrated_label" for k in kinds):
        overall_kind = "uncalibrated_label"
    else:
        overall_kind = "mixed"
    return {
        "answers": answers,
        "probabilities": probabilities,
        "decision_source": "legacy_json",
        "probability_kind": overall_kind,
        "question_probability_kinds": probability_kinds,
    }


def _model_family(model_id: str) -> str:
    lower = model_id.lower()
    for family, needles in _MODEL_FAMILIES:
        if any(needle in lower for needle in needles):
            return family
    return "custom"
