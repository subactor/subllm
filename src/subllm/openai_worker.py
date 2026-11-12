from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from contextlib import suppress
from http.client import HTTPException
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request

from .credential_env import credential_is_valid
from .errors import CompletionError
from .generation import token_limit
from .native_http import DEFAULT_TIMEOUT_SECONDS, decode_response_json, normalize_timeout
from .native_http import open_request as urlopen
from .policy import MODELS, PROVIDERS
from .policy_config import load_policy_config

_RUNTIME_POLICY = None
with suppress(Exception):
    _RUNTIME_POLICY = load_policy_config()

HTTP_SAFETY_PROFILE = "bounded-no-proxy-no-redirect-v1"
MAX_OPENAI_WORKER_REQUEST_BYTES = 4_000_000
MAX_OPENAI_RESPONSE_BYTES = 1_000_000


def _request(source: Any, *, transports=frozenset({"openai-compatible"}),
             schema="subllm.openai-worker-request/v1") -> Mapping[str, Any]:
    fields = {
        "schema", "provider", "api_base", "wire_model", "api_key", "messages",
        "model_parameters", "request_fields", "extra_headers", "response_format",
    }
    optional = {"capture_exchange", "timeout_seconds", "max_tokens"}
    if not isinstance(source, Mapping) or set(source) - optional != fields:
        raise CompletionError("OpenAI worker request must be a closed JSON object")
    if source.get("schema") != schema:
        raise CompletionError("API worker request schema is not supported")
    if "capture_exchange" in source and type(source["capture_exchange"]) is not bool:
        raise CompletionError("capture_exchange must be boolean")
    if "timeout_seconds" in source:
        try:
            normalize_timeout(source["timeout_seconds"])
        except ValueError:
            raise CompletionError("timeout_seconds must be a finite positive number") from None
    if "max_tokens" in source and (
        not isinstance(source["max_tokens"], int)
        or isinstance(source["max_tokens"], bool)
        or source["max_tokens"] <= 0
    ):
        raise CompletionError("max_tokens must be a positive integer")
    provider = source.get("provider")
    spec = PROVIDERS.get(provider) if isinstance(provider, str) else None
    if spec is None or spec.transport not in transports or source.get("api_base") != spec.api_base:
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
    # The one-shot worker reads the selected policy at process startup, together
    # with its provider catalogue. Reloading here can clear registered entries.
    runtime = _RUNTIME_POLICY
    if runtime is None:
        raise CompletionError("OpenAI worker policy is unavailable")
    ceilings = [value for value in (runtime.execution.max_output_tokens,
                                   runtime.execution.max_total_output_tokens) if value is not None]
    custom = runtime.custom_providers.get(provider)
    if custom is not None and "max_tokens" in dict(custom.model_parameters):
        ceilings.append(token_limit(dict(custom.model_parameters)["max_tokens"], legacy_string=True))
    requested = []
    if "max_tokens" in source:
        requested.append(token_limit(source["max_tokens"]))
    for parameters in (source["model_parameters"], source["request_fields"]):
        for name in ("max_tokens", "max_completion_tokens"):
            if name in parameters:
                requested.append(token_limit(parameters[name], legacy_string=True))
    if ceilings and requested and max(requested) > min(ceilings):
        raise CompletionError("OpenAI worker generation limit exceeds operator policy")
    if requested or ceilings:
        source = {**source, "max_tokens": min(requested + ceilings)}
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


def request_body(source: Mapping[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": source["wire_model"],
        "messages": source["messages"],
        **dict(source["model_parameters"]),
        **dict(source["request_fields"]),
    }
    limit = source.get("max_tokens", body.get("max_tokens"))
    if limit is not None:
        limit = token_limit(limit, legacy_string=True)
        body.pop("max_tokens", None)
        body.pop("max_completion_tokens", None)
        if "n" in body and (type(body["n"]) is not int or body["n"] != 1):
            raise CompletionError("bounded generation requires a single completion")
        body["max_completion_tokens" if source["provider"] == "codex" else "max_tokens"] = limit
    if source["response_format"] is not None:
        body["response_format"] = dict(source["response_format"])
    return body


def http_request(source, body):
    return Request(
        f"{str(source['api_base']).rstrip('/')}/chat/completions",
        data=json.dumps(body, ensure_ascii=True, separators=(",", ":")).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {source['api_key']}"} if source.get("api_key") else {}),
            **dict(source["extra_headers"]),
        },
        method="POST",
    )


def _execute(source: Mapping[str, Any]) -> Mapping[str, Any]:
    body = request_body(source)
    def finish(result, response=None):
        if not source.get("capture_exchange"):
            return result
        # Only API JSON bodies enter this private channel, never request headers or worker credentials.
        exchange = {"request": body, "response": response}
        def scrub(value):
            if isinstance(value, str):
                secret = str(source["api_key"])
                return value.replace(secret, "[credential removed]") if secret else value
            if isinstance(value, Mapping):
                return {scrub(key): scrub(item) for key, item in value.items()}
            if isinstance(value, list):
                return [scrub(item) for item in value]
            return value
        return {**result, "exchange": scrub(exchange)}

    request = http_request(source, body)
    timeout = normalize_timeout(source.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_OPENAI_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        status = exc.code
        error_body = None
        try:
            encoded_error = exc.read(1_000_001)
            error_body = (decode_response_json(encoded_error) if len(encoded_error) <= 1_000_000
                          else {"capture_status": "response_exceeds_limit"})
        except (ValueError, OSError, AttributeError, RecursionError):
            error_body = {"capture_status": "non_json_or_unreadable_error"}
        finally:
            exc.close()
        # A billing refusal cannot recover through pacing. Only fixed error
        # codes/types affect routing; arbitrary provider messages stay private.
        error = error_body.get("error") if isinstance(error_body, Mapping) else None
        quota_codes = {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached",
                       "project_spend_limit_exceeded", "organization_spend_limit_exceeded",
                       "organization_usage_limit_exceeded"}
        if status == 429 and isinstance(error, Mapping) and (
            (isinstance(error.get("code"), str) and error["code"] in quota_codes)
            or error.get("type") == "insufficient_quota"
            or (source.get("provider") == "zai" and error.get("code") == "1310")
        ):
            return finish(_error("quota_exhausted", provider_level=True, retryable=True), error_body)
        if status == 404:
            return finish(_error("model_unavailable", provider_level=False, retryable=True), error_body)
        retryable = status in {401, 402, 403, 408, 409, 425, 429} or status >= 500
        return finish(_error(f"http_{status}", provider_level=True, retryable=retryable), error_body)
    except HTTPException:
        return _error("invalid_response", provider_level=False, retryable=True)
    except TypeError:
        return _error("transport_error", provider_level=True, retryable=True)
    except (TimeoutError, URLError, OSError) as exc:
        is_timeout = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
        return _error(
            "timeout" if is_timeout else "transport_error",
            provider_level=True,
            retryable=True,
        )
    if len(payload) > MAX_OPENAI_RESPONSE_BYTES:
        return finish(_error("invalid_response", provider_level=False, retryable=True),
                      {"capture_status": "response_exceeds_limit"})
    raw = None
    try:
        raw = decode_response_json(payload)
        choice = raw["choices"][0]
        message = choice.get("message") if isinstance(choice, Mapping) else {}
        content = message.get("content") if isinstance(message, Mapping) else None
        finish_reason = str(choice.get("finish_reason") or "") if isinstance(choice, Mapping) else ""
        reasoning = (
            (message.get("reasoning_content") or message.get("reasoning"))
            if isinstance(message, Mapping) else None
        )
    except (ValueError, KeyError, IndexError, TypeError, RecursionError):
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
    except RecursionError:
        print("subllm-openai-worker: request exceeds JSON nesting limit", file=sys.stderr)
        return 2
    except (UnicodeError, json.JSONDecodeError, CompletionError) as exc:
        print(f"subllm-openai-worker: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
