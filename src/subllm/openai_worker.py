from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from contextlib import suppress
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .credential_env import credential_is_valid
from .errors import CompletionError
from .policy import MODELS, PROVIDERS
from .policy_config import load_policy_config

with suppress(Exception):
    load_policy_config()

MAX_OPENAI_WORKER_REQUEST_BYTES = 4_000_000


def _request(source: Any) -> Mapping[str, Any]:
    fields = {
        "schema", "provider", "api_base", "wire_model", "api_key", "messages",
        "model_parameters", "request_fields", "extra_headers", "response_format",
    }
    optional = {"capture_exchange", "timeout_seconds", "max_tokens"}
    if not isinstance(source, Mapping) or set(source) - optional != fields:
        raise CompletionError("OpenAI worker request must be a closed JSON object")
    if "capture_exchange" in source and type(source["capture_exchange"]) is not bool:
        raise CompletionError("capture_exchange must be boolean")
    if "timeout_seconds" in source and (
        not isinstance(source["timeout_seconds"], (int, float))
        or isinstance(source["timeout_seconds"], bool)
        or source["timeout_seconds"] <= 0
    ):
        raise CompletionError("timeout_seconds must be a positive number")
    if "max_tokens" in source and (
        not isinstance(source["max_tokens"], int)
        or isinstance(source["max_tokens"], bool)
        or source["max_tokens"] <= 0
    ):
        raise CompletionError("max_tokens must be a positive integer")
    provider = source.get("provider")
    spec = PROVIDERS.get(provider) if isinstance(provider, str) else None
    if spec is None or spec.transport != "openai-compatible" or source.get("api_base") != spec.api_base:
        raise CompletionError("OpenAI worker provider base is not policy-approved")
    wire_model = source.get("wire_model")
    if not isinstance(wire_model, str) or not wire_model or "\x00" in wire_model:
        raise CompletionError("OpenAI worker wire_model must be a non-empty safe string")
    api_key = source.get("api_key")
    if not isinstance(api_key, str) or "\x00" in api_key:
        raise CompletionError("OpenAI worker api_key must be a safe string")
    if spec.api_key_env:
        if not api_key:
            raise CompletionError("OpenAI worker api_key must be a non-empty safe string")
        if not credential_is_valid(provider, api_key):
            raise CompletionError("OpenAI worker credential does not match provider policy")
    elif api_key and not credential_is_valid(provider, api_key):
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
    }.get(provider, {"user"})
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


def _error(outcome: str, *, provider_level: bool, retryable: bool, message: str | None = None) -> Mapping[str, Any]:
    result: dict[str, Any] = {
        "schema": "subllm.openai-worker-result/v1",
        "status": "ERROR",
        "outcome": outcome,
        "provider_level": provider_level,
        "retryable": retryable,
    }
    if message is not None:
        result["message"] = message
    return result


def _execute(source: Mapping[str, Any]) -> Mapping[str, Any]:
    body: dict[str, Any] = {
        "model": source["wire_model"],
        "messages": source["messages"],
        **dict(source["model_parameters"]),
        **dict(source["request_fields"]),
    }
    if "max_tokens" in source:
        body["max_tokens"] = source["max_tokens"]
    elif "max_tokens" in body:
        with suppress(ValueError, TypeError):
            body["max_tokens"] = int(body["max_tokens"])
    if source["response_format"] is not None:
        body["response_format"] = dict(source["response_format"])
    def finish(result, response=None):
        if not source.get("capture_exchange"):
            return result
        # Only API JSON bodies enter this private channel, never request headers or worker credentials.
        exchange = {"request": body, "response": response}
        def scrub(value):
            if isinstance(value, str):
                return value.replace(str(source["api_key"]), "[credential removed]")
            if isinstance(value, Mapping):
                return {scrub(key): scrub(item) for key, item in value.items()}
            if isinstance(value, list):
                return [scrub(item) for item in value]
            return value
        return {**result, "exchange": scrub(exchange)}

    request = Request(
        f"{str(source['api_base']).rstrip('/')}/chat/completions",
        data=json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {source['api_key']}"} if source.get("api_key") else {}),
            **dict(source["extra_headers"]),
        },
        method="POST",
    )
    timeout = float(source["timeout_seconds"]) if "timeout_seconds" in source else None
    try:
        try:
            kwargs = {"timeout": timeout} if timeout is not None else {}
            with urlopen(request, **kwargs) as response:  # noqa: S310 - base is checked against fixed policy
                payload = response.read()
        except TypeError as exc:
            if "timeout" in str(exc):
                with urlopen(request) as response:  # noqa: S310
                    payload = response.read()
            else:
                raise
    except HTTPError as exc:
        status = exc.code
        error_body = None
        if source.get("capture_exchange"):
            try:
                encoded_error = exc.read(1_000_001)
                error_body = (json.loads(encoded_error) if len(encoded_error) <= 1_000_000
                              else {"capture_status": "response_exceeds_limit"})
            except (ValueError, OSError, AttributeError):
                error_body = {"capture_status": "non_json_or_unreadable_error"}
        if status == 404:
            return finish(_error("model_unavailable", provider_level=False, retryable=True), error_body)
        retryable = status in {401, 402, 403, 408, 409, 425, 429} or status >= 500
        return finish(_error(f"http_{status}", provider_level=True, retryable=retryable), error_body)
    except (TimeoutError, URLError, OSError) as exc:
        is_timeout = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
        return _error(
            "timeout" if is_timeout else "transport_error",
            provider_level=True,
            retryable=True,
        )
    raw = None
    try:
        raw = json.loads(payload.decode("utf-8"))
        choice = raw["choices"][0]
        message = choice.get("message") if isinstance(choice, Mapping) else {}
        content = message.get("content") if isinstance(message, Mapping) else None
        finish_reason = str(choice.get("finish_reason") or "") if isinstance(choice, Mapping) else ""
        reasoning = (
            (message.get("reasoning_content") or message.get("reasoning"))
            if isinstance(message, Mapping) else None
        )
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError):
        return finish(_error("invalid_response", provider_level=False, retryable=True), raw)
    if not isinstance(content, str) or not content:
        if finish_reason == "length" and isinstance(reasoning, str) and reasoning:
            usage = raw.get("usage") if isinstance(raw.get("usage"), Mapping) else {}
            details = usage.get("completion_tokens_details") if isinstance(usage, Mapping) else {}
            reasoning_tokens = (
                details.get("reasoning_tokens") if isinstance(details, Mapping) else None
            )
            if reasoning_tokens is not None:
                token_info = f" (reasoning consumed {reasoning_tokens} tokens)"
            else:
                token_info = f" (reasoning consumed {len(reasoning)} chars)"
            err = _error(
                "truncated",
                provider_level=True,
                retryable=True,
                message=f"Reasoning output truncated{token_info}",
            )
            if isinstance(usage, Mapping) and usage:
                err = {**err, "usage": dict(usage)}
            return finish(err, raw)
        return finish(_error("invalid_response", provider_level=False, retryable=True), raw)
    usage = raw.get("usage")
    return finish({
        "schema": "subllm.openai-worker-result/v1",
        "status": "SUCCESS",
        "content": content,
        "usage": dict(usage) if isinstance(usage, Mapping) else {},
        "finish_reason": str(choice.get("finish_reason") or ""),
    }, raw)


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
