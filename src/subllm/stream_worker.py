"""Policy-validated one-shot API stream worker; stdout contains bounded events."""
from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request

from . import anthropic_api, gemini_api, openai_worker
from .errors import CompletionError
from .native_http import MAX_ERROR_RESPONSE_BYTES, open_request
from .policy import PROVIDERS
from .stream_protocol import MAX_EVENT, NativeStream, sse_events

TRANSPORTS = frozenset({"openai-compatible", "anthropic", "gemini-sdk"})


def emit(kind, *, text="", data="", native_id="", native_type=""):
    frame = {"kind": kind, "text": text, "data": data, "native_id": native_id, "native_type": native_type}
    encoded = json.dumps(frame, ensure_ascii=True, separators=(",", ":"))
    if len(encoded) > MAX_EVENT * 2:
        raise ValueError("worker event bound exceeded")
    print(encoded, flush=True)


def request(source, transport):
    parameters = dict(source["model_parameters"])
    if "max_tokens" in source:
        parameters["max_tokens"] = source["max_tokens"]
    if transport == "openai-compatible":
        body = openai_worker.request_body(source)
        if body.get("n", 1) != 1:
            raise CompletionError("stream requires one completion")
        body.update(stream=True, stream_options={"include_usage": True})
        return openai_worker.http_request(source, body)
    if not source["api_base"].startswith("https://"):
        raise CompletionError("native stream requires HTTPS")
    module = anthropic_api if transport == "anthropic" else gemini_api
    body = module.request_body(source["wire_model"], source["messages"], source["response_format"], parameters)
    if transport == "anthropic":
        body["stream"] = True
        url = source["api_base"].rstrip("/") + "/messages"
        headers = {"x-api-key": source["api_key"], "anthropic-version": anthropic_api.ANTHROPIC_VERSION}
    else:
        url = (source["api_base"].rstrip("/") + "/models/" + quote(source["wire_model"], safe="")
               + ":streamGenerateContent?alt=sse")
        headers = {"x-goog-api-key": source["api_key"]}
    return Request(url, data=json.dumps(body, ensure_ascii=True).encode(),
                   headers={"Content-Type": "application/json", **headers}, method="POST")


def main():
    from .worker_lifetime import install_owner_guard
    install_owner_guard()
    state = None
    failure = {"outcome": "invalid_response", "retryable": False, "provider_level": False}
    try:
        encoded = sys.stdin.buffer.read(openai_worker.MAX_OPENAI_WORKER_REQUEST_BYTES + 1)
        if len(encoded) > openai_worker.MAX_OPENAI_WORKER_REQUEST_BYTES:
            raise ValueError("request bound exceeded")
        source = openai_worker._request(json.loads(encoded), transports=TRANSPORTS,
                                       schema="subllm.stream-worker-request/v1")
        transport = PROVIDERS[source["provider"]].transport
        state = NativeStream(transport, bounded="max_tokens" in source)
        wire = request(source, transport)
        with open_request(wire, timeout=source["timeout_seconds"]) as response:
            if response.headers.get_content_type() != "text/event-stream":
                raise ValueError("provider did not return SSE")
            emit("provider_event", native_type="opened")
            for event, identity, data in sse_events(response):
                for kind, text, value in state.feed(event, data):
                    if kind == "usage":
                        value = json.dumps({"usage": state.usage, "final": state.final_usage})
                    emit(kind, text=text, data=value, native_id=identity, native_type=event)
                emit("provider_event", native_id=identity, native_type=event or "message")
                if state.done:
                    break
            result = state.finish()
            result.pop("content")  # Parent already owns each accepted text delta.
            emit("result", data=json.dumps(result, ensure_ascii=True))
        return 0
    except HTTPError as error:
        status = error.code
        # Bounded drain/close, without exposing server text or credentials.
        error.read(MAX_ERROR_RESPONSE_BYTES + 1)
        error.close()
        failure = {"outcome": "model_unavailable" if status == 404 else f"http_{status}",
                   "retryable": status in {401, 402, 403, 404, 408, 409, 425, 429} or status >= 500,
                   "provider_level": status != 404}
    except (TimeoutError, URLError, OSError):
        failure = {"outcome": "transport_error", "retryable": True, "provider_level": True}
    except Exception:
        pass  # Only fixed diagnostics enter the public worker channel.
    if state is not None:
        usage = dict(state.usage)
        if not state.final_usage:
            for key in ("output_tokens", "completion_tokens", "total_tokens"):
                usage.pop(key, None)
        failure["partial"] = {"usage": usage,
                              "finish_reason": state.finish_reason, "tools": state.tools}
    emit("error", data=json.dumps(failure))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
