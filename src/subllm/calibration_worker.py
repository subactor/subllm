"""One bounded, policy-approved SSE probe; stdout contains metadata only."""
from __future__ import annotations

import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .errors import CompletionError
from .openrouter_routing import _controls, _number

MESSAGES = [{"role": "user", "content": "Reply exactly OK."}]
RESULT_SCHEMA = "subllm.calibration-sample/v1"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


urlopen = build_opener(_NoRedirect()).open


def result(outcome, started, *, clock=time.monotonic, **values):
    return {"schema": RESULT_SCHEMA, "outcome": outcome, "ttft_seconds": None,
            "first_reasoning_seconds": None, "total_seconds": max(0, clock() - started),
            "tokens_per_second": None, "input_tokens": None, "output_tokens": None,
            "cached_input_tokens": None, "cost_usd": None, **values}


def _count(value):
    if type(value) is not int or not 0 <= value <= 10**12:
        raise ValueError("invalid usage")
    return value


def parse_stream(response, started, *, clock=time.monotonic):
    """Ignore heartbeats; require terminal usage and DONE, never retain text."""
    first = reasoning = generated_first = generated_last = None
    finish = None
    usage = None
    size = 0
    event = []
    try:
        while True:
            line = response.readline(65537)
            size += len(line)
            if len(line) > 65536 or size > 1_000_000:
                return result("stream_limit", started, clock=clock)
            if not line:
                return result("incomplete_stream", started, clock=clock)
            line = line.decode("utf-8").rstrip("\r\n")
            if line.startswith(":"):
                continue
            if line.startswith("data:"):
                event.append(line[5:].lstrip(" "))
                continue
            if line or not event:
                continue
            data, event = "\n".join(event), []
            if data == "[DONE]":
                break
            frame = json.loads(data)
            if isinstance(frame, dict) and "error" in frame:
                error = frame["error"]
                code = error.get("code") if isinstance(error, dict) else None
                outcome = f"http_{code}" if type(code) is int and 100 <= code <= 599 else "stream_error"
                return result(outcome, started, clock=clock)
            if not isinstance(frame, dict):
                return result("stream_error", started, clock=clock)
            choices = frame.get("choices", [])
            if not isinstance(choices, list) or len(choices) > 1:
                return result("invalid_stream", started, clock=clock)
            if choices:
                choice = choices[0]
                delta = choice.get("delta", {})
                if not isinstance(delta, dict):
                    return result("invalid_stream", started, clock=clock)
                visible = isinstance(delta.get("content"), str) and bool(delta["content"])
                hidden = any(isinstance(delta.get(k), str) and delta[k] for k in ("reasoning", "reasoning_content"))
                if visible or hidden:
                    generated_last = clock() - started
                    if generated_first is None:
                        generated_first = generated_last
                if visible and first is None:
                    first = generated_last
                if hidden and reasoning is None:
                    reasoning = generated_last
                terminal = choice.get("finish_reason")
                if terminal is not None:
                    if finish is not None and finish != terminal:
                        return result("invalid_stream", started, clock=clock)
                    finish = terminal
            if "usage" in frame:
                usage = frame["usage"]
        if not isinstance(usage, dict):
            return result("billing_unknown", started, clock=clock)
        ni, no = _count(usage.get("prompt_tokens")), _count(usage.get("completion_tokens"))
        details = usage.get("prompt_tokens_details") or {}
        cached = _count(details.get("cached_tokens", 0))
        cost = _number(usage["cost"])
        if cached > ni:
            raise ValueError("invalid accounting")
        speed = (no / (generated_last - generated_first)
                 if generated_first is not None and generated_last > generated_first else None)
        outcome = "success" if finish == "stop" and first is not None else "truncated"
        return result(outcome, started, clock=clock, ttft_seconds=first,
                      first_reasoning_seconds=reasoning, tokens_per_second=speed,
                      input_tokens=ni, output_tokens=no, cached_input_tokens=cached, cost_usd=str(cost))
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeError, CompletionError):
        return result("invalid_stream", started, clock=clock)


def execute(envelope):
    from .openai_worker import _request

    if not isinstance(envelope, dict) or set(envelope) != {"schema", "request", "endpoint"}:
        raise CompletionError("invalid calibration envelope")
    if envelope["schema"] != "subllm.calibration-worker-request/v1":
        raise CompletionError("unsupported calibration envelope")
    source = _request(envelope["request"])
    params = source["model_parameters"]
    provider = params.get("provider", {})
    prices = provider.get("max_price", {})
    if not isinstance(prices, dict) or set(prices) != {"prompt", "completion", "request"} or prices["request"] != 0:
        raise CompletionError("calibration requires closed token caps and no request fee")
    _controls({**provider, "max_price": {k: v for k, v in prices.items() if k != "request"}})
    if (source["provider"] != "openrouter" or source["messages"] != MESSAGES
            or source["wire_model"] not in {"deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash-1017"}
            or source.get("capture_exchange") or source["response_format"] is not None
            or set(params) - {"provider", "max_tokens", "max_completion_tokens"}
            or type(params.get("max_tokens")) is not int or not 1 <= params["max_tokens"] <= 256
            or provider.get("only") != [envelope["endpoint"]]
            or provider.get("allow_fallbacks") is not False or provider.get("require_parameters") is not True):
        raise CompletionError("calibration requires a fixed bounded OpenRouter probe")
    if "max_completion_tokens" in params and (
            type(params["max_completion_tokens"]) is not int
            or not 1 <= params["max_completion_tokens"] <= params["max_tokens"]):
        raise CompletionError("inconsistent completion cap")
    body = {"model": source["wire_model"], "messages": MESSAGES, **params,
            **source["request_fields"], "stream": True, "stream_options": {"include_usage": True}}
    request = Request(source["api_base"].rstrip("/") + "/chat/completions",
                      data=json.dumps(body).encode(), method="POST", headers={
                          "Content-Type": "application/json", "Authorization": "Bearer " + source["api_key"],
                          **source["extra_headers"]})
    started = time.monotonic()
    try:
        with urlopen(request, timeout=source.get("timeout_seconds", 15)) as response:  # noqa: S310
            return parse_stream(response, started)
    except HTTPError as exc:
        return result(f"http_{exc.code}", started)
    except (TimeoutError, URLError, OSError):
        return result("transport_error", started)


def main():
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("oversized envelope")
        output = execute(json.loads(raw))
    except (CompletionError, ValueError, TypeError, KeyError):
        return 2
    print(json.dumps(output, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
