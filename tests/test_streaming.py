"""Native provider bytes, real workers and persistence; no paid credentials."""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path

import pytest

from subllm import GenerationBudget, interaction_store, stream_complete, usage
from subllm.stream_protocol import MAX_LINE, NativeStream, StreamProtocolError, sse_events


def sse(value, *, event="", identity=""):
    data = value if isinstance(value, str) else json.dumps(value)
    return ((f"event: {event}\n" if event else "") + (f"id: {identity}\n" if identity else "")
            + f"data: {data}\n\n").encode()


def openai_frames():
    return [sse({"choices": [{"index": 0, "delta": {"content": '{"value":'}, "finish_reason": None}]}),
            sse({"choices": [{"index": 0, "delta": {"content": "1}"}, "finish_reason": None}]}),
            sse({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
            sse({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2}}), sse("[DONE]")]


@contextmanager
def provider(frames, *, gate_at=None, status=200, tls=None):
    observed, started, release = [], threading.Event(), threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            observed.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(status)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Connection", "close")
            self.end_headers()
            try:
                for index, frame in enumerate(frames):
                    self.wfile.write(frame)
                    self.wfile.flush()
                    if index == gate_at:
                        started.set()
                        assert release.wait(30)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    if tls:
        import ssl
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(*tls)
        server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"{'https' if tls else 'http'}://127.0.0.1:{server.server_port}", observed, started, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(3)


def policy(monkeypatch, tmp_path, base, *, fallback=False):
    text = (Path(__file__).resolve().parents[1] / "subllm.toml").read_text()
    text = text.replace("enabled = true", "enabled = false")
    text += (f'\n[custom_providers.stream_fixture]\napi_base = "{base}/v1"\n'
             'default_model = "test-stream-model"\npriority = 1\nenabled = true\n'
             'routes = ["onedev-agent/code-edit"]\n')
    if fallback:
        text = text.replace("failover_enabled = false", "failover_enabled = true")
        text = re.sub(r"(?m)^max_attempts = \d+$", "max_attempts = 2", text, count=1)
        text += (f'\n[custom_providers.stream_backup]\napi_base = "{base}/v1"\n'
                 'default_model = "test-stream-backup"\npriority = 2\nenabled = true\n'
                 'routes = ["onedev-agent/code-edit"]\n')
    target = tmp_path / "policy.toml"
    target.write_text(text)
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(target))
    monkeypatch.setenv("SUBLLM_ARCHIVE_DIR", str(tmp_path / "archive"))
    monkeypatch.setattr(interaction_store, "_DEFAULT_STORE", None)


def test_live_delta_precedes_terminal_and_has_native_receipts(monkeypatch, tmp_path):
    budget = GenerationBudget(10)
    with provider(openai_frames(), gate_at=0) as (base, requests, started, release):
        policy(monkeypatch, tmp_path, base)
        with stream_complete("onedev-agent", "code-edit", [{"role": "user", "content": "test-prompt"}],
                             generation_budget=budget, quality_schema={"type": "object"}, epoch=7,
                             timeout_seconds=15) as stream:
            events = []
            for event in stream:
                events.append(event)
                if event.kind == "text_delta":
                    assert started.is_set() and stream.terminal is None
                    assert event.provisional and event.text == '{"value":'
                    feedback = stream.feedback(request_id=event.request_id, epoch=7, sequence=event.sequence)
                    assert feedback.accepted
                    release.set()
                    break
            events.extend(stream)
            result = stream.result()
            assert result.content == '{"value":1}' and result.audit.state == "stored"
            assert result.generation.output_tokens == budget.output_tokens == 2
            assert events[-1].kind == "completed" and not events[-1].provisional
            assert [event.sequence for event in events] == list(range(len(events)))
            assert len({event.attempt_id for event in events}) == 1
            assert stream.metrics.time_to_first_useful_feedback_seconds < stream.metrics.elapsed_seconds
            assert stream.metrics.maximum_queue_size <= stream.metrics.queue_capacity
            with pytest.raises(FrozenInstanceError):
                events[0].sequence = 0
    assert len(requests) == 1
    wire = requests[0][1]
    assert wire["stream"] is True and wire["stream_options"] == {"include_usage": True}
    assert wire["max_tokens"] == 10
    assert usage.query_usage({})["summary"]["attempts"] == 1


def test_stream_has_no_effect_until_iteration(monkeypatch, tmp_path):
    with provider(openai_frames()) as (base, requests, *_):
        policy(monkeypatch, tmp_path, base)
        stream = stream_complete("onedev-agent", "code-edit", [{"role": "user", "content": "test"}])
        assert requests == []
        assert stream.result().content == '{"value":1}'


def test_native_cached_input_survives_terminal_usage_without_double_debit(monkeypatch, tmp_path):
    budget = GenerationBudget(10)
    frames = openai_frames()
    frames[-2] = sse({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 2,
                                             "prompt_tokens_details": {"cached_tokens": 2}}})
    with provider(frames) as (base, requests, *_):
        policy(monkeypatch, tmp_path, base)
        result = stream_complete("onedev-agent", "code-edit", [{"role": "user", "content": "test"}],
                                 generation_budget=budget).result()
    assert result.usage == {"prompt_tokens": 3, "completion_tokens": 2, "cached_input_tokens": 2}
    assert result.generation.output_tokens == budget.output_tokens == 2 and len(requests) == 1


@pytest.mark.parametrize("fault", ["malformed", "missing_done", "bad_final_json", "conflicting_id"])
def test_partial_failure_never_retries_or_reports_success(monkeypatch, tmp_path, fault):
    frames = openai_frames()
    if fault == "malformed":
        frames[1] = b'data: {invalid\n\n'
    elif fault == "missing_done":
        frames.pop()
    elif fault == "bad_final_json":
        frames[1] = sse({"choices": [{"delta": {"content": "invalid"}, "finish_reason": None}]})
    else:
        frames[:2] = [sse({"choices": [{"delta": {"content": "a"}}]}, identity="test-id"),
                      sse({"choices": [{"delta": {"content": "b"}}]}, identity="test-id")]
    with provider(frames) as (base, requests, *_):
        policy(monkeypatch, tmp_path, base, fallback=True)
        budget = GenerationBudget(10)
        stream = stream_complete("onedev-agent", "code-edit", [{"role": "user", "content": "test"}],
                                 quality_schema={"type": "object"}, generation_budget=budget)
        events = list(stream)
        assert events[-1].kind == "error" and events[-1].provisional
        assert events[-1].response.audit.state == "stored"
        assert events[-1].response.audit.attempts[0].status == "error"
        assert len(requests) == 1
        assert budget.remaining_tokens == (8 if fault in {"missing_done", "bad_final_json"} else None)
        assert stream.metrics.invalidated_output_tokens == (2 if fault in {"missing_done", "bad_final_json"} else None)
        assert usage.query_usage({})["summary"]["attempts"] == 1


def test_http_refusal_before_output_keeps_native_policy_failover(monkeypatch, tmp_path):
    with provider([], status=429) as (base, requests, *_):
        policy(monkeypatch, tmp_path, base, fallback=True)
        events = list(stream_complete("onedev-agent", "code-edit", [{"role": "user", "content": "test"}]))
    assert len(requests) == 2 and events[-1].kind == "error"
    assert len(events[-1].response.audit.attempts) == 2
    assert len({event.attempt_id for event in events}) == 2


def test_missing_terminal_usage_is_unknown_not_zero(monkeypatch, tmp_path):
    frames = openai_frames()
    del frames[-2]
    with provider(frames) as (base, requests, *_):
        policy(monkeypatch, tmp_path, base)
        budget = GenerationBudget(10)
        result = stream_complete("onedev-agent", "code-edit", [{"role": "user", "content": "test"}],
                                 generation_budget=budget).result()
    assert result.generation.output_tokens is budget.remaining_tokens is None
    assert result.usage == {} and len(requests) == 1


def test_feedback_identity_and_acceptance_are_not_mutable(monkeypatch, tmp_path):
    observed = []
    with provider(openai_frames(), gate_at=0) as (base, requests, _, release):
        policy(monkeypatch, tmp_path, base)
        with stream_complete("onedev-agent", "code-edit", [{"role": "user", "content": "test"}], epoch=2,
                             quality_gate=lambda response: observed.append(response.content) is None) as stream:
            for event in stream:
                if event.kind != "text_delta":
                    continue
                binding = {"request_id": event.request_id, "epoch": event.epoch, "sequence": event.sequence}
                for changed in ({"request_id": "test-old"}, {"epoch": 1}, {"sequence": 100000},
                                {"action": "replace_tests"}):
                    assert not stream.feedback(**{**binding, **changed}).accepted
                    assert not stream.cancelled.is_set()
                assert stream.feedback(**binding).accepted
                release.set()
                break
            assert stream.result().content == '{"value":1}'
            assert not stream.feedback(**binding).accepted
    assert observed == ['{"value":1}'] and len(requests) == 1


def test_cancel_during_tool_fragment_ends_worker_without_executing_or_restarting(monkeypatch, tmp_path):
    from subllm import stream_transport
    spawned = []
    real = stream_transport.subprocess.Popen

    def popen(*args, **kwargs):
        process = real(*args, **kwargs)
        spawned.append(process)
        return process

    monkeypatch.setattr(stream_transport.subprocess, "Popen", popen)
    frames = [sse({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "test-call",
                "function": {"name": "test_tool", "arguments": '{"value":'}}]}}]})]
    with provider(frames, gate_at=0) as (base, requests, _, release):
        policy(monkeypatch, tmp_path, base, fallback=True)
        budget = GenerationBudget(10)
        with stream_complete("onedev-agent", "code-edit", [{"role": "user", "content": "test"}],
                             generation_budget=budget) as stream:
            for event in stream:
                if event.kind == "tool_call_delta":
                    feedback = stream.feedback(request_id=event.request_id, epoch=event.epoch,
                                               sequence=event.sequence, action="restart")
                    assert feedback.accepted and feedback.disposition == "restart_required"
                    break
            terminal = stream.close()
            release.set()
            assert terminal.kind == "cancelled" and terminal.response.audit.state == "stored"
            assert stream.metrics.invalidated_output_tokens is None
            assert not stream.capabilities.executes_tools and not stream.capabilities.resumes_prefixes
    assert len(requests) == len(spawned) == 1 and spawned[0].poll() is not None
    assert budget.remaining_tokens is None


def test_saturated_receiver_has_bounded_queue_and_deadline(monkeypatch, tmp_path):
    with provider(openai_frames(), gate_at=0) as (base, requests, _, release):
        policy(monkeypatch, tmp_path, base)
        stream = stream_complete("onedev-agent", "code-edit", [{"role": "user", "content": "test"}],
                                 queue_capacity=1, timeout_seconds=2)
        stream.__enter__()
        assert stream._done.wait(30)
        release.set()
        assert stream.terminal.kind == "error" and stream.worker is None
        assert stream.metrics.maximum_queue_size == 1
        assert stream.terminal.error_code == "SUBLLM-STREAM-BACKPRESSURE-TIMEOUT"
        assert len(requests) == 1


def test_sse_multiline_and_explicit_id_deduplication():
    frame = b'id: 1\ndata: {"choices":\ndata: []}\n\n'
    assert list(sse_events(BytesIO(frame + frame))) == [("", "1", '{"choices":\n[]}')]


@pytest.mark.parametrize("payload", [b"data: {}", b"data: " + b"x" * MAX_LINE + b"\n\n",
                                      b"id: x\ndata: a\n\nid: x\ndata: b\n\n",
                                      b"event: a\nid: x\ndata: same\n\nevent: b\nid: x\ndata: same\n\n"])
def test_sse_bounds_and_truncation_fail_closed(payload):
    with pytest.raises((StreamProtocolError, ValueError)):
        list(sse_events(BytesIO(payload)))


def test_completion_id_is_not_an_event_id_and_duplicate_text_is_legitimate():
    state = NativeStream("openai-compatible")
    for _ in range(2):
        state.feed("", json.dumps({"id": "same-completion", "choices": [{"delta": {"content": "ha"}}]}))
    state.feed("", json.dumps({"choices": [{"delta": {}, "finish_reason": "stop"}]}))
    state.feed("", "[DONE]")
    assert state.finish()["content"] == "haha"


@pytest.mark.parametrize("raw", [
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "x"}},
    {"type": "message_stop"},
])
def test_anthropic_rejects_out_of_order_events(raw):
    with pytest.raises(StreamProtocolError):
        NativeStream("anthropic").feed(raw["type"], json.dumps(raw))


@pytest.fixture(scope="module")
def native_tls(tmp_path_factory):
    folder = tmp_path_factory.mktemp("stream-tls")
    cert, key = folder / "cert.pem", folder / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                    "-subj", "/CN=stream-test", "-addext",
                    "subjectAltName=DNS:api.anthropic.com,DNS:generativelanguage.googleapis.com",
                    "-keyout", str(key), "-out", str(cert)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    key.chmod(0o600)
    return cert, key


def anthropic_frames():
    records = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 3, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": '{"value":'}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "1}"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
        {"type": "message_stop"},
    ]
    return [sse(record, event=record["type"]) for record in records]


def gemini_frames():
    return [sse({"candidates": [{"content": {"parts": [{"text": '{"value":'}]}}]}),
            sse({"candidates": [{"content": {"parts": [{"text": "1}"}]}, "finishReason": "STOP"}],
                 "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 2,
                                   "thoughtsTokenCount": 1, "totalTokenCount": 6}})]


@pytest.mark.parametrize("provider_id,frames,gate,output", [
    ("claude", anthropic_frames, 2, 2), ("agy", gemini_frames, 0, 3),
])
def test_real_native_tls_stream_reuses_policy_and_wire_limits(
    monkeypatch, tmp_path, native_tls, provider_id, frames, gate, output,
):
    from subllm import MODELS, PROVIDERS, client_routes, resolve
    with provider(frames(), gate_at=gate, tls=native_tls) as (base, requests, _, release):
        root = Path(__file__).resolve().parents[1]
        target = tmp_path / "native-policy.toml"
        target.write_text((root / "subllm.toml").read_text())
        monkeypatch.setenv("SUBLLM_POLICY_FILE", str(target))
        monkeypatch.setenv("SUBLLM_ARCHIVE_DIR", str(tmp_path / "archive"))
        monkeypatch.setattr(interaction_store, "_DEFAULT_STORE", None)
        seed = resolve("onedev-agent", "code-edit", provider="zai", environ={"ZAI_API_KEY": "test.stream"})
        spec = PROVIDERS[provider_id]
        model = next(model for model in MODELS.values() if provider_id in model.providers and not model.forbidden)
        remote = model.providers[provider_id]
        route = replace(seed, provider=provider_id, transport=spec.transport, model=model.id,
                        wire_model=remote.wire_model, litellm_model=remote.litellm_model, api_base=spec.api_base,
                        api_key_env=spec.api_key_env, model_parameters={})
        monkeypatch.setattr(client_routes, "available_routes", lambda *a, **kw: [route])
        monkeypatch.setattr(client_routes, "order_with_last_resort", lambda routes, **kw: routes)
        # Only this child interpreter maps the approved hostname to loopback.
        # Production URL/base validation and certificate hostname checks remain.
        (tmp_path / "sitecustomize.py").write_text(
            'import socket\n_original=socket.getaddrinfo\n'
            'def loopback(host,port,*args,**kwargs):\n'
            '    if host not in {"api.anthropic.com","generativelanguage.googleapis.com"}:\n'
            '        raise OSError("test denies nonfixture network")\n'
            f'    return _original("127.0.0.1",{int(base.rsplit(":", 1)[1])},*args,**kwargs)\n'
            'socket.getaddrinfo=loopback\n'
        )
        monkeypatch.setenv("PYTHONPATH", str(tmp_path) + os.pathsep + os.environ.get("PYTHONPATH", ""))
        monkeypatch.setenv("SSL_CERT_FILE", str(native_tls[0]))
        with stream_complete("onedev-agent", "code-edit", [{"role": "user", "content": "test"}],
                             generation_limits={"max_output_tokens": 8}) as stream:
            for event in stream:
                if event.kind == "text_delta":
                    assert stream.terminal is None
                    release.set()
                    break
            result = stream.result()
        assert result.content == '{"value":1}' and result.generation.output_tokens == output
        assert result.audit.state == "stored" and len(requests) == 1
        wire = requests[0][1]
        if provider_id == "claude":
            assert wire["stream"] is True and wire["max_tokens"] == 8
        else:
            assert requests[0][0].endswith(":streamGenerateContent?alt=sse")
            assert wire["generationConfig"]["maxOutputTokens"] == 8
