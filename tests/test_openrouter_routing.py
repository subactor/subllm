from __future__ import annotations

import json
from decimal import Decimal

import pytest

from subllm.errors import CompletionError
from subllm.openrouter_routing import apply_parameters, rank_endpoints

MODEL = "deepseek/deepseek-v4.1-flash"


def endpoint(tag, prompt, completion, **fields):
    return {"tag": tag, "provider_name": tag, "status": 0, "pricing": {
        "prompt": prompt, "completion": completion,
    }, "supported_parameters": ["tools", "response_format"], **fields}


def quote(rows, **kwargs):
    return rank_endpoints({"data": {"id": MODEL, "endpoints": rows}}, model=MODEL,
                          observed_at=100, now=110, input_tokens=100_000, output_tokens=1000, **kwargs)


def test_cost_depends_on_token_mix_and_discount_is_already_applied():
    rows = [endpoint("input-cheap", ".00000002", ".000001"),
            endpoint("output-cheap", ".0000000537", ".0000002148", pricing={
                "prompt": ".0000000537", "completion": ".0000002148", "discount": .821})]
    assert quote(rows)[0]["tag"] == "input-cheap"
    ranked = rank_endpoints({"data": {"id": MODEL, "endpoints": rows}}, model=MODEL,
                            observed_at=100, now=110, input_tokens=1000, output_tokens=100_000)
    assert ranked[0]["tag"] == "output-cheap"
    assert Decimal(ranked[0]["estimated_cost_usd"]) == Decimal(".0215337")


def test_cache_and_per_request_fees_are_counted_once():
    row = endpoint("cache", ".000001", ".000002")
    row["pricing"].update(input_cache_read=".00000001", request=".001")
    result = quote([row], cached_input_tokens=90_000)[0]
    assert Decimal(result["estimated_cost_usd"]) == Decimal(".0139")


def test_unknown_latency_is_not_zero_and_hard_latency_constraint_excludes_it():
    unknown = endpoint("unknown", "0", "0")
    known = endpoint("known", ".0000001", ".0000001",
                     latency_last_30m={"p90": .5}, throughput_last_30m={"p90": 100})
    assert quote([unknown])[0]["estimated_seconds"] is None
    assert quote([unknown, known], max_ttft_seconds=1)[0]["tag"] == "known"
    assert quote([unknown, known], latency_penalty_usd_per_second=".001")[0]["tag"] == "known"


def test_quote_filters_budget_status_capabilities_and_context():
    rows = [endpoint("down", "0", "0", status=-1),
            endpoint("small", "0", "0", context_length=100),
            endpoint("no-tools", "0", "0", supported_parameters=[]),
            endpoint("expensive", "1", "1"), endpoint("ok", ".0000001", ".0000002")]
    assert [r["tag"] for r in quote(rows, required_parameters=["tools"], max_cost_usd=".02")] == ["ok"]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", True, "garbage"])
def test_invalid_prices_are_not_eligible(bad):
    assert quote([endpoint("invalid", bad, "0")]) == []


def test_stale_or_wrong_model_snapshot_fails_closed():
    with pytest.raises(CompletionError):
        quote([], max_age_seconds=1)
    with pytest.raises(CompletionError):
        rank_endpoints({"data": {"id": "another-model", "endpoints": []}}, model=MODEL,
                       observed_at=100, now=110, input_tokens=1, output_tokens=1)


def test_overflowing_remote_metrics_prices_and_latency_cap_fail_closed():
    assert quote([endpoint("bad-metric", "0", "0", latency_last_30m={"p90": "1e999"})]) == []
    assert quote([endpoint("bad-price", "1e999999999", "0")]) == []
    with pytest.raises(CompletionError):
        quote([], max_ttft_seconds="1e999")


def policy_file(tmp_path, row):
    path = tmp_path / "routing.json"
    path.write_text(json.dumps({"schema": "subllm.openrouter-routing/v1", "models": {MODEL: row}}))
    return {"SUBLLM_OPENROUTER_POLICY_FILE": str(path)}


def test_controls_keep_existing_tighter_output_cap_and_do_not_touch_other_providers(tmp_path):
    env = policy_file(tmp_path, {"sort": "price", "only": ["baidu/fp8", "relace"],
                                "max_price": {"prompt": "0.1", "completion": "0.6"},
                                "preferred_max_latency": 2, "max_tokens": 1000})
    params = apply_parameters("openrouter", MODEL, {"max_tokens": "500"}, environ=env)
    assert params["max_tokens"] == 500
    assert params["provider"]["only"] == ["baidu/fp8", "relace"]
    assert params["provider"]["max_price"]["completion"] == .6
    assert apply_parameters("agy", MODEL, {}, environ=env) == {}
    assert apply_parameters("openrouter", "other-model", {}, environ=env) == {}


@pytest.mark.parametrize("row", [{"sort": "random"}, {"only": []}, {"allow_fallbacks": True},
                                  {"max_tokens": True}, {"max_price": {"prompt": -1}},
                                  {"preferred_max_latency": float("inf")}, {"typo": 1}])
def test_invalid_or_unbounded_controls_fail_closed(tmp_path, row):
    with pytest.raises(CompletionError):
        apply_parameters("openrouter", MODEL, {}, environ=policy_file(tmp_path, row))


def test_existing_provider_constraints_cannot_be_overwritten(tmp_path):
    with pytest.raises(CompletionError):
        apply_parameters("openrouter", MODEL, {"provider": {"zdr": True}},
                         environ=policy_file(tmp_path, {"sort": "price"}))


def test_controls_reach_both_policy_routes_and_catalog_worker_payload(tmp_path, monkeypatch):
    from subllm import configured_routes
    from subllm.client_workers import _complete_openai_compatible
    from subllm.proxy import _build_model_resolved_routes

    env = {**policy_file(tmp_path, {"sort": "price", "max_tokens": 512}),
           "OPENROUTER_API_KEY": "test-openrouter-credential-value", "SUBLLM_PROVIDER_ORDER": "openrouter"}
    route = configured_routes("subactor-proxy", "deepseek-flash", environ=env)[0]
    assert route.model_parameters["provider"]["sort"] == "price"
    catalog = _build_model_resolved_routes("deepseek-v4.1-flash", environ=env)[0]
    captured = []

    def worker(request, **kwargs):
        captured.append(request)
        return {"status": "SUCCESS", "content": "OK", "usage": {}, "finish_reason": "stop"}

    monkeypatch.setattr("subllm.client_workers._run_openai_worker", worker)
    _complete_openai_compatible(catalog, [{"role": "user", "content": "OK"}],
                                timeout_seconds=1, request_id=None, response_format=None)
    assert captured[0]["max_tokens"] == 512
    assert captured[0]["model_parameters"]["provider"]["sort"] == "price"
    assert captured[0]["wire_model"] == MODEL
