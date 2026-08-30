from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .credential_env import credential_is_valid
from .errors import CompletionError
from .policy import MODELS, PROVIDERS

MAX_OPENAI_WORKER_REQUEST_BYTES = 4_000_000


def _request(source: Any) -> Mapping[str, Any]:
    fields = {
        "schema", "provider", "api_base", "wire_model", "api_key", "messages",
        "model_parameters", "request_fields", "extra_headers", "response_format",
    }
    if not isinstance(source, Mapping) or set(source) != fields:
        raise CompletionError("OpenAI worker request must be a closed JSON object")
    if source.get("schema") != "subllm.openai-worker-request/v1":
        raise CompletionError("OpenAI worker request schema is not supported")
    provider = source.get("provider")
    spec = PROVIDERS.get(provider) if isinstance(provider, str) else None
    if spec is None or spec.transport != "openai-compatible" or source.get("api_base") != spec.api_base:
        raise CompletionError("OpenAI worker provider base is not policy-approved")
    for field in ("wire_model", "api_key"):
        value = source.get(field)
        if not isinstance(value, str) or not value or "\x00" in value:
            raise CompletionError(f"OpenAI worker {field} must be a non-empty safe string")
    if not credential_is_valid(provider, source["api_key"]):
        raise CompletionError("OpenAI worker credential does not match provider policy")
    if not any(
        provider in model.providers and model.providers[provider].wire_model == source["wire_model"]
        for model in MODELS.values()
    ):
        raise CompletionError("OpenAI worker model is not policy-approved for provider")
    messages = source.get("messages")
    if (
        not isinstance(messages, list)
        or not 1 <= len(messages) <= 128
        or any(not isinstance(message, Mapping) for message in messages)
    ):
        raise CompletionError("OpenAI worker messages must contain 1 to 128 objects")
    for field in ("model_parameters", "request_fields", "extra_headers"):
        if not isinstance(source.get(field), Mapping):
            raise CompletionError(f"OpenAI worker {field} must be an object")
    allowed_request_fields = {
        "zai": {"request_id", "user_id"},
        "openrouter": {"user"},
    }.get(provider, set())
    if set(source["request_fields"]) - allowed_request_fields:
        raise CompletionError("OpenAI worker request fields are not provider-approved")
    for key, value in source["extra_headers"].items():
        if (
            not isinstance(key, str)
            or not isinstance(value, str)
            or key.lower() in {"authorization", "content-type"}
            or "\r" in key + value
            or "\n" in key + value
        ):
            raise CompletionError("OpenAI worker extra headers are not safe")
    if source.get("response_format") is not None and not isinstance(source["response_format"], Mapping):
        raise CompletionError("OpenAI worker response_format must be an object or null")
    return source


def _error(outcome: str, *, provider_level: bool, retryable: bool) -> Mapping[str, Any]:
    return {
        "schema": "subllm.openai-worker-result/v1",
        "status": "ERROR",
        "outcome": outcome,
        "provider_level": provider_level,
        "retryable": retryable,
    }


def _execute(source: Mapping[str, Any]) -> Mapping[str, Any]:
    body: dict[str, Any] = {
        "model": source["wire_model"],
        "messages": source["messages"],
        **dict(source["model_parameters"]),
        **dict(source["request_fields"]),
    }
    if source["response_format"] is not None:
        body["response_format"] = dict(source["response_format"])
    request = Request(
        f"{str(source['api_base']).rstrip('/')}/chat/completions",
        data=json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {source['api_key']}",
            "Content-Type": "application/json",
            **dict(source["extra_headers"]),
        },
        method="POST",
    )
    try:
        with urlopen(request) as response:  # noqa: S310 - base is checked against fixed policy
            payload = response.read()
    except HTTPError as exc:
        status = exc.code
        if status == 404:
            return _error("model_unavailable", provider_level=False, retryable=True)
        retryable = status in {401, 403, 408, 409, 425, 429} or status >= 500
        return _error(f"http_{status}", provider_level=True, retryable=retryable)
    except (TimeoutError, URLError, OSError) as exc:
        return _error(
            "timeout" if isinstance(exc, TimeoutError) else "transport_error",
            provider_level=True,
            retryable=True,
        )
    try:
        raw = json.loads(payload.decode("utf-8"))
        choice = raw["choices"][0]
        content = choice["message"]["content"]
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        return _error("invalid_response", provider_level=False, retryable=True)
    if not isinstance(content, str) or not content:
        return _error("invalid_response", provider_level=False, retryable=True)
    usage = raw.get("usage")
    return {
        "schema": "subllm.openai-worker-result/v1",
        "status": "SUCCESS",
        "content": content,
        "usage": dict(usage) if isinstance(usage, Mapping) else {},
        "finish_reason": str(choice.get("finish_reason") or ""),
    }


def main() -> int:
    try:
        encoded = sys.stdin.buffer.read(MAX_OPENAI_WORKER_REQUEST_BYTES + 1)
        if len(encoded) > MAX_OPENAI_WORKER_REQUEST_BYTES:
            raise CompletionError("OpenAI worker request exceeds 4000000 bytes")
        request = _request(json.loads(encoded.decode("utf-8")))
        result = _execute(request)
    except (UnicodeError, json.JSONDecodeError, CompletionError) as exc:
        print(f"subllm-openai-worker: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
