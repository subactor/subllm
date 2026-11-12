"""Registered proxy routes deliver actual provider deltas and native receipts."""
from __future__ import annotations

import json
import socket
import struct
import threading
from contextlib import contextmanager
from urllib.request import Request, urlopen

import pytest
from test_streaming import openai_frames, policy, provider

from subllm import make_proxy_server, usage


@contextmanager
def proxy_server(monkeypatch):
    import subllm.proxy as module
    monkeypatch.setattr(module, "is_upstream_ollama_alive", lambda *args: False)
    server = make_proxy_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


@pytest.mark.parametrize("path", ["/v1/chat/completions", "/api/chat"])
def test_proxy_flushes_before_provider_finishes_and_has_terminal_receipt(monkeypatch, tmp_path, path):
    with provider(openai_frames(), gate_at=0) as (upstream, requests, _, release):
        policy(monkeypatch, tmp_path, upstream)
        with proxy_server(monkeypatch) as base:
            payload = {"model": "onedev-agent/code-edit", "messages": [{"role": "user", "content": "test"}],
                       "stream": True, "stream_options": {"include_usage": True}}
            request = Request(base + path, data=json.dumps(payload).encode(),
                              headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=20) as response:
                chunks = []
                while True:
                    line = response.readline()
                    if not line:
                        break
                    if line.startswith(b"data: "):
                        line = line[6:]
                    if not line.strip() or line.strip() == b"[DONE]" or line.startswith(b":"):
                        continue
                    chunk = json.loads(line)
                    chunks.append(chunk)
                    text = (chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if path.startswith("/v1") and chunk.get("choices") else
                            chunk.get("message", {}).get("content", ""))
                    if text:
                        assert not release.is_set() or text == "1}"
                        if not release.is_set():
                            assert text == '{"value":'
                            release.set()
                terminal = next(chunk for chunk in reversed(chunks) if "subllm" in chunk)
                assert terminal["subllm"]["audit"]["state"] == "stored"
                assert not terminal["subllm"]["provisional"]
                if path.startswith("/v1"):
                    assert terminal["usage"]["completion_tokens"] == 2
                else:
                    assert terminal["done"] and terminal["eval_count"] == 2
    assert len(requests) == usage.query_usage({})["summary"]["attempts"] == 1


def test_proxy_partial_failure_never_sends_a_success_stop(monkeypatch, tmp_path):
    with provider(openai_frames()[:-1]) as (upstream, requests, *_):
        policy(monkeypatch, tmp_path, upstream, fallback=True)
        with proxy_server(monkeypatch) as base:
            payload = {"model": "onedev-agent/code-edit", "messages": [{"role": "user", "content": "test"}],
                       "stream": True}
            request = Request(base + "/v1/chat/completions", data=json.dumps(payload).encode(),
                              headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=20) as response:
                body = response.read().decode()
    assert "[DONE]" not in body and '"error"' in body
    assert '"state": "stored"' in body and len(requests) == 1


def test_proxy_marks_missing_usage_unknown(monkeypatch, tmp_path):
    frames = openai_frames()
    del frames[-2]
    with provider(frames) as (upstream, requests, *_):
        policy(monkeypatch, tmp_path, upstream)
        with proxy_server(monkeypatch) as base:
            payload = {"model": "onedev-agent/code-edit", "messages": [{"role": "user", "content": "test"}],
                       "stream": True, "stream_options": {"include_usage": True}}
            request = Request(base + "/v1/chat/completions", data=json.dumps(payload).encode(),
                              headers={"Content-Type": "application/json"})
            with urlopen(request, timeout=20) as response:
                chunks = [json.loads(line[6:]) for line in response if line.startswith(b"data: {")]
    assert chunks[-1]["usage"] is None and len(requests) == 1


@pytest.mark.parametrize("mode", ["disconnect", "slow"])
def test_proxy_cancels_a_disconnected_or_stalled_receiver(monkeypatch, tmp_path, mode):
    from test_streaming import sse

    import subllm.proxy as module
    import subllm.proxy_stream as adapter

    created = []
    original = adapter.CompletionStream

    def capture(*args, **kwargs):
        stream = original(*args, **kwargs)
        created.append(stream)
        return stream

    monkeypatch.setattr(adapter, "CompletionStream", capture)
    if mode == "slow":
        setup = module.SubLLMProxyHandler.setup

        def small_buffer(self):
            setup(self)
            self.connection.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1024)

        monkeypatch.setattr(module.SubLLMProxyHandler, "setup", small_buffer)
        frames = [sse({"choices": [{"delta": {"content": "t" * 8192}}]}) for _ in range(100)]
    else:
        frames = openai_frames()
    with provider(frames, gate_at=0 if mode == "disconnect" else None) as (upstream, requests, _, release):
        policy(monkeypatch, tmp_path, upstream)
        with proxy_server(monkeypatch) as base:
            payload = {"model": "onedev-agent/code-edit", "messages": [{"role": "user", "content": "test"}],
                       "stream": True, "timeout": 30}
            request = Request(base + "/v1/chat/completions", data=json.dumps(payload).encode(),
                              headers={"Content-Type": "application/json"})
            response = urlopen(request, timeout=60)
            try:
                if mode == "disconnect":
                    while b'"content"' not in response.readline():
                        pass
                    peer = response.fp.raw._sock
                    peer.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                    response.close()
                assert created[0]._done.wait(20)
                assert created[0].terminal.kind == "cancelled"
                assert created[0].worker is None and created[0].terminal.response.audit.state == "stored"
                assert len(requests) == 1
            finally:
                response.close()
                release.set()


def test_synthetic_controller_checkpoint_and_cycle_observations(monkeypatch, tmp_path):
    """Measure a controlled SDK/checkpoint cycle, never qualify real Forge performance."""
    import hashlib
    import math
    import sys
    import time
    from dataclasses import asdict
    from pathlib import Path

    from test_streaming import sse

    from subllm import stream_complete

    prefix = "def value():\n    return 1\n"
    full = prefix + "qualifier = 'complete'\n"
    frames = [sse({"choices": [{"delta": {"content": prefix}}]}),
              sse({"choices": [{"delta": {"content": full[len(prefix):]}}]}), *openai_frames()[2:]]
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()
    intent = json.loads((Path(__file__).resolve().parents[1] / "project/ticket-214/intent.json").read_text())
    manifest = json.dumps({"value": 1, "qualifier": "complete"}, sort_keys=True)
    manifest_path = tmp_path / "test-manifest.json"
    manifest_path.write_text(manifest)
    manifest_path.chmod(0o444)
    observations = []
    with provider(frames, gate_at=0) as (upstream, requests, _, release):
        policy(monkeypatch, tmp_path, upstream)
        for sample in range(20):
            release.clear()
            cycle_start = time.monotonic()
            with stream_complete("onedev-agent", "code-edit", [{"role": "user", "content": "fixture"}],
                                 timeout_seconds=15) as stream:
                for event in stream:
                    if event.kind != "text_delta":
                        continue
                    assert event.text == prefix and stream.terminal is None
                    # Execute only this exact trusted fixture. A prefix test passes,
                    # while the fixed full manifest still rejects this fragment.
                    namespace = {}
                    exec(compile(prefix, "trusted-prefix-fixture", "exec"), namespace)
                    assert namespace["value"]() == 1 and "qualifier" not in namespace
                    assert event.provisional and not stream.capabilities.qualifies_code_checkpoints
                    feedback = stream.feedback(request_id=event.request_id, epoch=event.epoch,
                                               sequence=event.sequence)
                    assert feedback.accepted
                    release.set()
                    break
                response = stream.result()
            assert response.content == full and response.audit.state == "stored"
            checkpoint = tmp_path / f"checkpoint-{sample}.py"
            checkpoint.write_text(response.content)
            checkpoint.chmod(0o444)
            assert checkpoint.read_text() == full  # Never execute untrusted model output.
            binding = {"base": intent["delivery"]["acceptedBaseSha"],
                       "spec": digest("value() == 1 and qualifier == complete"),
                       "environment": digest(sys.version), "test_manifest": digest(manifest),
                       "code": digest(checkpoint.read_text())}
            accepted = {}
            exec(compile(full, str(checkpoint), "exec"), accepted)
            expected = json.loads(manifest_path.read_text())
            assert accepted["value"]() == expected["value"] and accepted["qualifier"] == expected["qualifier"]
            observations.append({"binding": binding, "qualified_by": "synthetic-test-controller",
                                 "full_cycle_seconds": time.monotonic() - cycle_start,
                                 "stream": asdict(stream.metrics)})
    assert len(requests) == usage.query_usage({})["summary"]["attempts"] == 20
    cycles = sorted(row["full_cycle_seconds"] for row in observations)
    assert all(0 < row["stream"]["time_to_first_useful_feedback_seconds"] < row["full_cycle_seconds"]
               for row in observations)
    report = {"scope": "synthetic-sdk-controller-cycle", "samples": observations,
              "p95_full_cycle_seconds": cycles[math.ceil(0.95 * len(cycles)) - 1],
              "pricing_currency": None, "whole_forge_cycle": "NOT_RUN", "hard_real_time": False}
    (tmp_path / "s6-stream-benchmark.json").write_text(json.dumps(report, indent=2) + "\n")
