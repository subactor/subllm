from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from .errors import PoaContractError

IDENTIFIER = re.compile(r"^[a-z][a-z0-9._:-]*$")
PROCESS_REF = re.compile(r"^poa://[a-z0-9.-]+/process/[a-z][a-z0-9._:-]*/v[1-9][0-9]*$")
CAPABILITY_REF = re.compile(r"^capability://[a-z0-9.-]+/[a-z][a-z0-9._:/-]*/v[1-9][0-9]*$")
POLICY_REF = re.compile(r"^policy://[a-z0-9.-]+/[a-z][a-z0-9._:/-]*/v[1-9][0-9]*$")
PROCESS_URI = re.compile(
    r"^[a-z][a-z0-9+.-]*://[A-Za-z0-9._:-]+"
    r"(?:/[A-Za-z0-9._:-]+)*/(?:query|command)/[A-Za-z0-9._:-]+$"
)
TARGET_REF = re.compile(r"^target://[a-z0-9.-]+/[A-Za-z0-9._:/-]+$")
ADAPTER_REF = re.compile(r"^adapter://[a-z0-9.-]+/[A-Za-z0-9._:/-]+/v[1-9][0-9]*$")
ARTIFACT_REF = re.compile(r"^artifact://[a-z0-9.-]+/[A-Za-z0-9._:/-]+/r[1-9][0-9]*$")
SCHEMA_REF = re.compile(r"^schema://[a-z0-9.-]+/[A-Za-z0-9._:/-]+/v[1-9][0-9]*$")
GRAMMAR_REF = re.compile(r"^grammar://[a-z0-9.-]+/[A-Za-z0-9._:/-]+/v[1-9][0-9]*$")
SUBJECT = re.compile(r"^(?:human|agent|service|mcp):[a-zA-Z0-9._:-]+$")
IDEMPOTENCY = re.compile(r"^[A-Za-z0-9._:-]{8,160}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SHA256_REF = re.compile(r"^sha256:[a-f0-9]{64}$")

TARGET = "target://subactor.subllm/workspace-policy"
ADAPTER = "adapter://subactor.subllm/policy-resolver/v1"
POLICY = "policy://subactor.subllm/llm-route/v1"
VERIFY_CAPABILITY = "capability://subactor.subllm/policy/read-back/v1"
VERIFY_SCHEMA = "schema://subactor.subllm/public-view/v1"
INPUT_SCHEMA = "schema://subactor.subllm/closed-request/v1"
OUTPUT_SCHEMA = "schema://subactor.subllm/public-view/v1"
OBSERVATION_FACTS = "artifact://subactor.subllm/observations/policy-facts/r1"
ROUTE_INPUT = "artifact://subactor.subllm/inputs/route-request/r1"
GRAMMAR = "grammar://subactor.subllm/poa-request/v1"


def exact(value: Any, required: set[str], optional: set[str] | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PoaContractError("POA-DOC-001", "document must be an object")
    extra = set(value) - required - (optional or set())
    missing = required - set(value)
    if extra or missing:
        raise PoaContractError("POA-DOC-001", "document fields are not closed")
    return dict(value)


def require_pattern(value: Any, label: str, pattern: re.Pattern[str], code: str = "POA-REF-001") -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise PoaContractError(code, f"{label} is not a closed reference")
    return value


def require_id(value: Any, label: str) -> str:
    return require_pattern(value, label, IDENTIFIER, "POA-ID-001")
