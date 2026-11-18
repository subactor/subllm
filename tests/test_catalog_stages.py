"""Error-path pins for compile_catalog's validation stages (SUB-08)."""

from __future__ import annotations

import copy

import pytest

from subllm.catalog import compile_catalog, export_catalog
from subllm.errors import InvalidPolicyError


def _doc():
    return copy.deepcopy(export_catalog())


def _first(mapping):
    return next(iter(mapping))


def _mutations():
    def provider_binding(d):
        d["providers"][_first(d["providers"])]["api_base"] = "https://evil.example"

    def provider_priority_clash(d):
        enabled = [k for k, v in d["providers"].items() if v["enabled"]]
        d["providers"][enabled[1]]["priority"] = d["providers"][enabled[0]]["priority"]

    def default_model_missing(d):
        d["providers"][_first(d["providers"])]["default_model"] = "no-such-model"

    def model_bad_variants(d):
        d["models"][_first(d["models"])]["providers"] = {"no-such-provider": {}}

    def model_bad_alias(d):
        model = next(m for m in d["models"].values() if m["providers"])
        variant = next(iter(model["providers"].values()))
        variant["litellm_model"] = None

    def app_short_id(d):
        d["applications"]["abc"] = {"title": "x", "url": "https://example.org"}

    def app_http_url(d):
        d["applications"][_first(d["applications"])]["url"] = "http://example.org"

    def route_unknown_app(d):
        d["routes"][0]["application"] = "no-such-application"

    def route_duplicate(d):
        d["routes"].append(copy.deepcopy(d["routes"][0]))

    def route_no_candidates(d):
        d["routes"][0]["candidates"] = []

    def candidate_extra_field(d):
        d["routes"][0]["candidates"][0]["extra"] = 1

    def candidate_unknown_provider(d):
        d["routes"][0]["candidates"][0]["provider"] = "no-such-provider"

    def candidate_unknown_model(d):
        d["routes"][0]["candidates"][0]["model"] = "no-such-model"

    def candidate_bad_parameters(d):
        d["routes"][0]["candidates"][0]["model_parameters"] = {"temperature": "high"}

    def candidate_duplicate(d):
        d["routes"][0]["candidates"].append(copy.deepcopy(d["routes"][0]["candidates"][0]))

    def unsupported_version(d):
        d["version"] = 2

    return [
        (provider_binding, "bindings cannot change"),
        (provider_priority_clash, "unique priorities"),
        (default_model_missing, "default model must be permitted"),
        (model_bad_variants, "invalid model provider variants"),
        (model_bad_alias, "invalid model alias"),
        (app_short_id, "6..128 characters"),
        (app_http_url, "public HTTPS"),
        (route_unknown_app, "unknown/duplicate route"),
        (route_duplicate, "unknown/duplicate route"),
        (route_no_candidates, "1..32 candidates"),
        (candidate_extra_field, "invalid candidate fields"),
        (candidate_unknown_provider, "unknown candidate provider"),
        (candidate_unknown_model, "unavailable or forbidden"),
        (candidate_bad_parameters, "bounded overrides"),
        (candidate_duplicate, "duplicate candidate|unique effective priorities"),
        (unsupported_version, "unsupported version"),
    ]


def test_exported_catalog_compiles_with_stable_digest():
    first, second = compile_catalog(_doc()), compile_catalog(_doc())
    assert first.sha256 == second.sha256 and first.canonical_json == second.canonical_json
    assert first.routes and first.models and first.applications


@pytest.mark.parametrize(("mutate", "message"), _mutations(), ids=lambda v: getattr(v, "__name__", None))
def test_each_stage_rejects_its_invalid_input(mutate, message):
    document = _doc()
    mutate(document)
    with pytest.raises(InvalidPolicyError, match=message):
        compile_catalog(document)


def test_null_candidate_model_has_the_same_identity_as_an_omitted_one():
    omitted, nulled = _doc(), _doc()
    candidate = next(c for r in nulled["routes"] for c in r["candidates"] if "model" not in c)
    candidate["model"] = None
    assert compile_catalog(omitted).sha256 == compile_catalog(nulled).sha256
