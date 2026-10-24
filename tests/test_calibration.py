from __future__ import annotations

import copy
import io
import json
import subprocess
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from subllm import calibration as c
from subllm import calibration_worker as w
from subllm.errors import CompletionError

MODEL = "deepseek-v4.1-flash-1017"
WIRE = "deepseek/" + MODEL


def snapshot():
    return {"data": {"id": WIRE, "endpoints": [{
        "tag": tag, "status": 0, "provider_name": tag, "pricing": {
            "prompt": "0.0000001", "completion": "0.0000002"},
        "context_length": 10000, "max_completion_tokens": 1000,
    } for tag in ("a/fp8", "b/fp8")]}}


def run(**kwargs):
    return c.calibrate(snapshot(), model=MODEL, observed_at=100, now=101,
                       endpoints=["a/fp8", "b/fp8"], max_cost_usd=".001", **kwargs)


def success(**changes):
    return {**w.result("success", 0, clock=lambda: 1), "ttft_seconds": .5,
            "input_tokens": 34, "output_tokens": 4, "cached_input_tokens": 0,
            "cost_usd": ".00001", **changes}


@pytest.fixture
def live(monkeypatch):
    calls, records, health = [], [], []
    route = SimpleNamespace(provider="openrouter", wire_model=WIRE, api_base="https://openrouter.ai/api/v1",
                            api_key="redacted", extra_headers={}, model_parameters={},
                            provider_request_fields=lambda **_: {"user": "subactor-proxy"})
    monkeypatch.setattr(c, "merged_environment", lambda **_: {})
    monkeypatch.setattr(c, "load_policy_config", lambda **_: SimpleNamespace(
        source=None, source_sha256="a" * 64, execution=SimpleNamespace(attempt_timeout_seconds=15)))
    monkeypatch.setattr(c, "resolve_attempt_timeout", lambda *_, **__: 15)
    monkeypatch.setattr(c, "_build_model_resolved_routes", lambda *_, **__: [route])
    monkeypatch.setattr(c, "order_by_health", lambda routes, **_: routes)
    monkeypatch.setattr(c, "record_attempt", lambda **kw: records.append(kw))
    monkeypatch.setattr(c, "record_success", lambda *_, **kw: health.append(("success", kw)))
    monkeypatch.setattr(c, "record_failure", lambda *_, **kw: health.append(("failure", kw)))
    monkeypatch.setattr(c.time, "time", lambda: 101)

    def invoke(request, endpoint, timeout, **kw):
        calls.append((request, endpoint, timeout))
        return success()

    monkeypatch.setattr(c, "_invoke", invoke)
    return route, calls, records, health


def test_dry_run_never_resolves_credentials_or_calls_a_provider(monkeypatch):
    def forbidden(**_):
        raise AssertionError("dry-run touched live context")

    monkeypatch.setattr(c, "merged_environment", forbidden)
    report = run(samples=20)
    assert report["live"] is False and report["samples"] == []
    assert report["stop_reason"] == "budget_limit"
    assert len(report["planned_endpoints"]) == 9


@pytest.mark.parametrize("kwargs", [{"samples": True}, {"samples": 21}, {"max_tokens": 257},
                                  {"timeout_seconds": float("nan")}, {"timeout_seconds": 31}])
def test_campaign_bounds_are_closed(kwargs):
    with pytest.raises(CompletionError):
        run(**kwargs)


def test_stale_duplicate_and_request_fee_snapshots_fail_before_dispatch():
    with pytest.raises(CompletionError):
        c.calibrate(snapshot(), model=MODEL, observed_at=1, now=1000, endpoints=["a/fp8"], max_cost_usd=".1")
    for duplicate in (True, False):
        data = snapshot()
        if duplicate:
            data["data"]["endpoints"].append(copy.deepcopy(data["data"]["endpoints"][0]))
        else:
            data["data"]["endpoints"][0]["pricing"]["request"] = ".01"
        with pytest.raises(CompletionError):
            c.calibrate(data, model=MODEL, observed_at=100, now=101, endpoints=["a/fp8"], max_cost_usd=".1")


def test_reservations_stop_before_the_next_paid_call(live):
    report = run(samples=20, live=True)
    assert len(live[1]) == 9 and len(live[2]) == 9
    assert report["stop_reason"] == "budget_limit"
    request = live[1][0][0]
    assert request["messages"] == w.MESSAGES
    assert request["model_parameters"]["provider"]["only"] == ["a/fp8"]
    assert request["model_parameters"]["provider"]["max_price"]["request"] == 0
    assert "redacted" not in json.dumps(report)
    assert "Reply exactly OK" not in json.dumps(report)


def test_shared_cooldown_blocks_every_request(live, monkeypatch):
    monkeypatch.setattr(c, "order_by_health", lambda *_, **__: ())
    assert run(live=True)["stop_reason"] == "account_cooldown"
    assert not live[1] and not live[2]


@pytest.mark.parametrize("outcome", ["http_403", "http_402", "billing_unknown", "truncated"])
def test_failure_stops_without_retry_and_keeps_reservation(live, monkeypatch, outcome):
    monkeypatch.setattr(c, "_invoke", lambda *_, **__: w.result(outcome, 0, clock=lambda: 1))
    report = run(live=True, samples=10)
    assert report["stop_reason"] == outcome and len(report["samples"]) == 1
    assert float(report["reserved_cost_usd"]) > 0
    assert len(live[2]) == 1
    assert bool(live[3]) == outcome.startswith("http_")


def test_unknown_or_excess_accounting_prevents_another_call(live, monkeypatch):
    monkeypatch.setattr(c, "_invoke", lambda *_, **__: success(cost_usd="1"))
    report = run(live=True, samples=3)
    assert report["stop_reason"] == "accounting_limit" and len(report["samples"]) == 1
    assert live[2][0]["status"] == "error"
    assert [q["tag"] for q in c.rank_calibrated(snapshot(), report, now=102)] == ["b/fp8"]


def test_snapshot_must_still_be_fresh_before_each_paid_dispatch(live, monkeypatch):
    monkeypatch.setattr(c.time, "time", lambda: 1001)
    report = run(live=True)
    assert report["stop_reason"] == "snapshot_stale" and not live[1]


def test_policy_drift_stops_before_another_paid_request(live, monkeypatch):
    policies = iter([SimpleNamespace(source=None, source_sha256="a", execution=None),
                     SimpleNamespace(source_sha256="b")])
    monkeypatch.setattr(c, "load_policy_config", lambda **_: next(policies))
    assert run(live=True)["stop_reason"] == "policy_drift"
    assert not live[1]


def test_operator_caps_and_specific_endpoint_constraints_are_preserved(live):
    route = live[0]
    route.model_parameters = {"max_tokens": 10, "max_completion_tokens": 5,
                              "provider": {"only": ["a"], "max_price": {"prompt": .01}}}
    with pytest.raises(CompletionError):
        run(live=True)  # b is excluded: preflight must reject before dispatching a.
    assert not live[1]
    request = c._request_for(route, "a/fp8", snapshot()["data"]["endpoints"][0], 32, 15)
    assert request["model_parameters"]["max_tokens"] == request["model_parameters"]["max_completion_tokens"] == 5
    assert request["model_parameters"]["provider"]["max_price"]["prompt"] == .01
    route.model_parameters = {"provider": {"only": ["a/fp8"]}}
    with pytest.raises(CompletionError):
        c._request_for(route, "a/fp8/flex", snapshot()["data"]["endpoints"][0], 32, 15)


def test_cancellation_stops_and_keeps_unknown_billing_reserved(live, monkeypatch):
    def cancel(*_, **__):
        raise KeyboardInterrupt

    monkeypatch.setattr(c, "_invoke", cancel)
    report = run(live=True, samples=3)
    assert report["stop_reason"] == "cancelled" and len(report["samples"]) == 1
    assert float(report["reserved_cost_usd"]) > 0


def test_parent_watchdog_reaps_the_isolated_worker(monkeypatch):
    reaped = []
    process = SimpleNamespace(communicate=lambda *_, **__: (_ for _ in ()).throw(
        subprocess.TimeoutExpired("probe", 1)))
    monkeypatch.setattr(c.subprocess, "Popen", lambda *_, **__: process)
    monkeypatch.setattr(c, "_terminate_worker_process_group", lambda p: reaped.append(p))
    assert c._invoke({}, "a", 1)["outcome"] == "timeout"
    assert reaped == [process]


def event(delta=None, finish=None, usage=None):
    frame = {"choices": [{"delta": delta or {}, "finish_reason": finish}]}
    if usage is not None:
        frame["usage"] = usage
    return ("data: " + json.dumps(frame) + "\n\n").encode()


USAGE = {"prompt_tokens": 34, "completion_tokens": 4, "cost": .00001}


def test_sse_separates_heartbeat_reasoning_visible_ttft_and_terminal_accounting():
    encoded = (b": heartbeat\n\n" + event({"reasoning": "hidden-private-text"})
               + event({"content": "private-A"}) + event({"content": "private-B"}, "stop")
               + event(finish="stop", usage=USAGE) + b"data: [DONE]\n\n")
    clock = iter([.2, .8, 1, 1.2])
    output = w.parse_stream(io.BytesIO(encoded), 0, clock=lambda: next(clock))
    assert output["outcome"] == "success" and output["ttft_seconds"] == .8
    assert output["first_reasoning_seconds"] == .2 and output["total_seconds"] == 1.2
    assert output["tokens_per_second"] == 5
    assert "private" not in json.dumps(output)


@pytest.mark.parametrize(("raw", "outcome"), [
    (b'data: {"error":{"message":"secret-upstream-error"}}\n\n', "stream_error"),
    (b'data: {"error":{"code":402,"message":"secret-credit-error"}}\n\n', "http_402"),
    (event({"content": "secret"}), "incomplete_stream"),
    (event({"content": "secret"}, "stop") + b'data: [DONE]\n\n', "billing_unknown"),
    (b"data: " + b"x" * 65536 + b"\n\n", "stream_limit"),
    (b"data: not-json\n\n", "invalid_stream"),
])
def test_malformed_partial_and_error_streams_do_not_become_success(raw, outcome):
    output = w.parse_stream(io.BytesIO(raw), 0, clock=lambda: 1)
    assert output["outcome"] == outcome
    assert "secret" not in json.dumps(output)


def test_probe_worker_reuses_approved_provider_model_and_never_captures_exchange(live, monkeypatch):
    captured = []

    class Response(io.BytesIO):
        pass

    def open_request(request, **_):
        captured.append(json.loads(request.data))
        return Response(event({"content": "OK"}, "stop", USAGE) + b"data: [DONE]\n\n")

    monkeypatch.setattr(w, "urlopen", open_request)
    source = c._request_for(live[0], "a/fp8", snapshot()["data"]["endpoints"][0], 32, 15)
    envelope = {"schema": "subllm.calibration-worker-request/v1", "request": source, "endpoint": "a/fp8"}
    assert w.execute(envelope)["outcome"] == "success"
    assert captured[0]["stream"] and captured[0]["stream_options"]["include_usage"]
    assert "redacted" not in repr(captured)
    source["api_base"] = "https://unapproved.invalid"
    with pytest.raises(CompletionError):
        w.execute(envelope)
    assert len(captured) == 1


def test_provider_http_error_is_secret_free_and_redirects_are_disabled(live, monkeypatch):
    def fail(request, **_):
        raise HTTPError(request.full_url, 403, "redacted", {}, None)

    monkeypatch.setattr(w, "urlopen", fail)
    source = c._request_for(live[0], "a/fp8", snapshot()["data"]["endpoints"][0], 32, 15)
    output = w.execute({"schema": "subllm.calibration-worker-request/v1", "request": source, "endpoint": "a/fp8"})
    assert output["outcome"] == "http_403" and "credential" not in json.dumps(output)
    assert w._NoRedirect().redirect_request(None, None, 302, "", {}, "https://unapproved.invalid") is None


def test_only_fresh_distinct_same_profile_samples_affect_fixed_workload_quotes(live):
    report = run(live=True, samples=6)
    ranked = c.rank_calibrated(snapshot(), report, now=102, latency_penalty_usd_per_second=".001")
    assert all(r["local_samples"] == 3 and r["local_ttft_seconds"] == .5 for r in ranked)
    assert all(r["local_ttft_seconds"] is None for r in c.rank_calibrated(snapshot(), report, now=102, quantile="p90"))
    bad = copy.deepcopy(report)
    bad["samples"].append(copy.deepcopy(bad["samples"][0]))
    with pytest.raises(CompletionError):
        c.rank_calibrated(snapshot(), bad, now=102)
    for key, value in [("profile", "other"), ("snapshot_observed_at", 0), ("output_token_cap", 10000)]:
        bad = {**report, key: value}
        with pytest.raises(CompletionError):
            c.rank_calibrated(snapshot(), bad, now=1000 if key == "snapshot_observed_at" else 102)
