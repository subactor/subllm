from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .errors import InvalidPolicyError
from .policy_config import load_policy_config
from .resolver import configured_routes

SCHEMA = "subllm.routing-contract/v1"


def export_routing_contract(application: str, function: str) -> dict[str, Any]:
    """Export operator policy, independently of caller credentials/order overrides."""
    from .poa.canonical import digest_document

    candidates = configured_routes(application, function, environ={})
    document = {
        "schema": SCHEMA,
        "version": 1,
        "application": application,
        "function": function,
        "candidates": [candidate.public_dict() for candidate in candidates],
        "execution": {
            key: str(value) if isinstance(value, float) else value
            for key, value in asdict(load_policy_config().execution).items()
        },
    }
    return {**document, "sha256": digest_document(document)}


def verify_routing_contract(
    document: dict[str, Any], *, expected_sha256: str, application: str, function: str,
) -> dict[str, Any]:
    """An embedded hash is not authority: require an independently pinned digest."""
    from .poa.canonical import digest_document

    fields = {"schema", "version", "application", "function", "candidates", "execution", "sha256"}
    if not isinstance(document, dict) or set(document) != fields:
        raise InvalidPolicyError("invalid routing contract fields")
    if document["schema"] != SCHEMA or type(document["version"]) is not int or document["version"] != 1:
        raise InvalidPolicyError("unsupported routing contract version")
    if (document["application"], document["function"]) != (application, function):
        raise InvalidPolicyError("routing contract profile mismatch")
    payload = {key: value for key, value in document.items() if key != "sha256"}
    if document["sha256"] != expected_sha256 or digest_document(payload) != expected_sha256:
        raise InvalidPolicyError("routing contract digest mismatch")
    if not isinstance(document["candidates"], list) or not document["candidates"]:
        raise InvalidPolicyError("routing contract has no candidates")
    return document
