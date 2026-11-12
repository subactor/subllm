"""Live formatting of the same native stream for OpenAI SSE and Ollama chat."""
from __future__ import annotations

import json
import time
from dataclasses import asdict
from uuid import uuid4

from .generation import output_count
from .streaming import CompletionStream


def _usage(response):
    usage = response.usage
    source = usage.get("input_tokens", usage.get("prompt_tokens"))
    target = output_count(usage)
    if type(source) is not int or source < 0 or target is None:
        return None
    if "total_tokens" in usage and (type(usage["total_tokens"]) is not int or usage["total_tokens"] != source + target):
        return None
    from .proxy import _openai_usage
    return _openai_usage(usage)


def _receipts(event):
    response = event.response
    return {"request_id": event.request_id, "epoch": event.epoch, "attempt_id": event.attempt_id,
            "sequence": event.sequence, "provisional": event.provisional,
            "audit": asdict(response.audit) if response.audit is not None else None,
            "generation": asdict(response.generation) if response.generation is not None else None}


def _tool_delta(value, event):
    if isinstance(value, list):
        return value
    index = value.get("index", 0)
    if "partial_json" in value:
        return [{"index": index, "function": {"arguments": value["partial_json"]}}]
    arguments = value.get("input", value.get("args", {}))
    return [{"index": index, "id": value.get("id") or f"call-{event.attempt_id}-{index}", "type": "function",
             "function": {"name": value.get("name"), "arguments": json.dumps(arguments) if arguments else ""}}]


def serve_stream(handler, payload, model, app, function, timeout, request_id, ticket, *, protocol, created):
    request_id = request_id or "ollama-" + uuid4().hex
    def invoke():
        return handler._execute_model_or_route(model, payload["messages"], app, function,
                                               timeout, request_id, payload)
    stream = CompletionStream(invoke, request_id=request_id, timeout_seconds=timeout)
    sent_headers = False
    emitted_text = False
    original_timeout = handler.connection.gettimeout()

    def write(value):
        remaining = stream.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        handler.connection.settimeout(min(1.0, remaining))
        data = json.dumps(value, ensure_ascii=True)
        handler.wfile.write((f"data: {data}\n\n" if protocol == "openai" else data + "\n").encode())
        handler.wfile.flush()

    def chunk(event, text="", tools=None, finish=None):
        metadata = {"request_id": event.request_id, "epoch": event.epoch, "attempt_id": event.attempt_id,
                    "sequence": event.sequence, "provisional": event.provisional}
        if protocol == "openai":
            delta = {"content": text} if text else {}
            if not emitted_text and text:
                delta["role"] = "assistant"
            if tools is not None:
                delta["tool_calls"] = _tool_delta(tools, event)
            return {"id": request_id, "object": "chat.completion.chunk", "created": created,
                    "model": event.model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                    "subllm": metadata}
        return {"model": event.model, "created_at": created,
                "message": {"role": "assistant", "content": text}, "done": False,
                "subllm": metadata,
                **({"subllm_tool_delta": tools} if tools is not None else {})}

    try:
        with stream:
            handler.connection.settimeout(min(1.0, timeout))
            while True:
                try:
                    event = stream._poll(0.25)
                except StopIteration:
                    return
                if event is None:
                    if sent_headers:
                        if protocol == "openai":
                            handler.wfile.write(b": keepalive\n\n")
                            handler.wfile.flush()
                        else:
                            write({"model": stream.model, "created_at": created,
                                   "message": {"role": "assistant", "content": ""}, "done": False,
                                   "subllm": {"request_id": request_id, "heartbeat": True,
                                              "provisional": True}})
                    continue
                opened = event.kind == "provider_event" and event.native_type == "opened"
                if event.kind not in {"text_delta", "tool_call_delta", "completed", "cancelled",
                                      "error", "tool_required"} and not opened:
                    continue
                terminal = event.response is not None
                if not sent_headers:
                    if terminal and event.kind != "completed":
                        if stream._failure is not None and handler._handle_contract_error(stream._failure):
                            return
                        handler._error(502, event.error_code or "SUBLLM-STREAM-FAILED",
                                       "inference stream did not complete")
                        return
                    handler.close_connection = True
                    handler.send_response(200)
                    handler._send_cors_headers()
                    handler.send_header("Content-Type", "text/event-stream; charset=utf-8" if protocol == "openai"
                                        else "application/x-ndjson; charset=utf-8")
                    handler.send_header("Cache-Control", "no-cache")
                    handler.send_header("Connection", "close")
                    handler.send_header("X-Subactor-Provider", event.provider)
                    handler.send_header("X-Subactor-Model", event.model)
                    if ticket:
                        handler.send_header("X-Subactor-Ticket", ticket)
                    handler.end_headers()
                    sent_headers = True
                if opened:
                    continue
                if not terminal:
                    write(chunk(event, text=event.text,
                                tools=json.loads(event.data) if event.kind == "tool_call_delta" else None))
                    emitted_text |= bool(event.text)
                    continue
                if event.kind != "completed":
                    write({"error": {"code": event.error_code, "message": "inference stream did not complete"},
                           "subllm": _receipts(event)})
                    return  # Never send a false stop/[DONE] after a partial failure.
                response = event.response
                if not emitted_text and response.content:
                    # A caller-supplied test adapter may return a complete result.
                    # It is one final delta, never simulated incremental inference.
                    write(chunk(event, text=response.content))
                usage = _usage(response)
                if protocol == "openai":
                    final = chunk(event, finish=response.finish_reason)
                    final["subllm"] = _receipts(event)
                    write(final)
                    if (isinstance(payload.get("stream_options"), dict)
                            and payload["stream_options"].get("include_usage")):
                        write({**final, "choices": [], "usage": usage})
                    handler.wfile.write(b"data: [DONE]\n\n")
                    handler.wfile.flush()
                else:
                    write({"model": response.model, "created_at": created,
                           "message": {"role": "assistant", "content": ""}, "done": True,
                           "total_duration": int(stream.metrics.elapsed_seconds * 1_000_000_000),
                           "prompt_eval_count": usage["prompt_tokens"] if usage else None,
                           "eval_count": usage["completion_tokens"] if usage else None,
                           "subllm": _receipts(event)})
                from .proxy import _write_proxy_receipt
                _write_proxy_receipt(ticket, app or "subactor-proxy", function or "chat", model,
                                     response, round(stream.metrics.elapsed_seconds * 1000))
    except (BrokenPipeError, ConnectionResetError, TimeoutError, OSError):
        stream.cancel()
    finally:
        stream.close()
        handler.connection.settimeout(original_timeout)
