from copy import deepcopy

import pytest

from subllm import InvalidPolicyError, UnknownRouteError, configured_routes
from subllm.poa import EventStore, PolicyBus
from subllm.poa.registry import EXPORT_CONTRACT_URI
from subllm.routing_contract import export_routing_contract, verify_routing_contract


def test_bus_contract_is_exact_profile_and_query_only():
    store = EventStore()
    result = PolicyBus(store).query({
        "schema": "subllm.query/v1", "process_uri": EXPORT_CONTRACT_URI,
        "application": "platform", "function": "interactive",
    })
    assert store.sequence == 0
    assert result["candidates"] == [r.public_dict() for r in configured_routes("platform", "interactive", environ={})]
    assert verify_routing_contract(result, expected_sha256=result["sha256"],
                                   application="platform", function="interactive") == result
    assert result != export_routing_contract("validator-agent", "direct-pr-review")


def test_contract_is_independent_of_secrets_and_caller_allowlist(monkeypatch):
    expected = export_routing_contract("platform", "interactive")
    monkeypatch.setenv("SUBLLM_PROVIDER_ORDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-not-a-real-secret")
    assert export_routing_contract("platform", "interactive") == expected
    assert "test-not-a-real-secret" not in str(expected)


def test_contract_rejects_tampered_artifact_and_wrong_profile():
    original = export_routing_contract("platform", "interactive")
    changed = deepcopy(original)
    changed["candidates"][0]["wire_model"] = "unapproved-model"
    for document, app, function, digest in [
        (changed, "platform", "interactive", original["sha256"]),
        (original, "validator-agent", "direct-pr-review", original["sha256"]),
        (original, "platform", "interactive", "0" * 64),
        ({**original, "version": 2}, "platform", "interactive", original["sha256"]),
    ]:
        with pytest.raises(InvalidPolicyError):
            verify_routing_contract(document, expected_sha256=digest, application=app, function=function)


def test_unknown_profile_is_not_substituted():
    with pytest.raises(UnknownRouteError):
        export_routing_contract("platform", "unknown-function")
