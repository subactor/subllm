#!/usr/bin/env python3
"""Dependency-free conformance checker for wellmanifest.logs/v1."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


CONTRACT_PATH = Path("contracts/logs.contract.v0.5.json")
LEGACY_CONTRACT_PATHS = (
    Path("contracts/logs.contract.json"),
    Path("contracts/logs.contract.v0.3.json"),
    Path("contracts/logs.contract.v0.4.json"),
)
HELP_PATH = "errors/LOGS-VALIDATION-001.md"
DIAGNOSTIC_CODE = "LOGS-VALIDATION-001"
ZERO_HASH = "0" * 64
MAX_ADOPTED_SCHEMA_BYTES = 1024 * 1024
MAX_ADOPTED_CATALOG_BYTES = 64 * 1024
MAX_ERROR_DOCUMENT_BYTES = 256 * 1024
CODE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
NAMESPACE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,31}$")
STREAM_RE = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
EVENT_ID_RE = re.compile(r"^event:[A-Za-z0-9._:-]{2,122}$")
ACTOR_RE = re.compile(r"^(?:human|agent|service):[A-Za-z0-9._:-]+$")
OWNER_RE = re.compile(r"^(?:human|agent|service|unresolved):[A-Za-z0-9._:-]+$")
SUBJECT_RE = re.compile(r"^[a-z][a-z0-9+.-]*:[A-Za-z0-9._:/-]+$")
# A reserved core type is a bare identifier; a deployment type is namespaced and
# may never squat the reserved "logs." namespace.
DOMAIN_TYPE_RE = re.compile(r"^(?!logs\.)[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*)+$")
SOURCE_RE = re.compile(r"^[a-z][a-z0-9]*(?:\.[a-z][a-z0-9_]*)*$")
STATE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
RECEIPT_RE = re.compile(
    r"^receipt://[a-z0-9][a-z0-9.-]{0,63}"
    r"(?:/[A-Za-z0-9][A-Za-z0-9._:-]{0,63}){1,8}$"
)
ENDPOINT_REF_RE = re.compile(
    r"^(?:endpoint:[A-Za-z0-9._:/-]+|https?://"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?|\[[0-9A-Fa-f:.]+\])"
    r"(?::[1-9][0-9]{0,4})?)$"
)
TRANSPORT_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")
REMEDIATION_REF_RE = re.compile(r"^(?:error|knowledge|runbook)://[A-Za-z0-9._:/-]+$")
TRACE_ID_RE = re.compile(r"^[a-f0-9]{32}$")
SPAN_ID_RE = re.compile(r"^[a-f0-9]{16}$")
PATH_RE = re.compile(r"^(?!/)(?!.*(?:^|/)\.\.(?:/|$))[A-Za-z0-9._/-]+$")
SHA_RE = re.compile(r"^[a-f0-9]{64}$")
DATETIME_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T(?:[01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]"
    r"(?:\.[0-9]{1,9})?Z$"
)
ARTIFACT_RE = re.compile(
    r"^artifact://[a-z0-9.-]+/[A-Za-z0-9._:/-]+/r[1-9][0-9]*$"
)
REQUIRED_ERROR_SECTIONS = (
    "Error DSL",
    "Situation",
    "Meaning",
    "Safe resolution",
    "Verification",
    "Do not",
    "Related events",
)
EXPECTED_PROCESSES = {
    "inspect": "logs://repository/contracts/query/inspect",
    "validate": "logs://repository/events/query/validate",
    "planAppend": "logs://stream/events/query/plan-append",
    "append": "logs://stream/events/command/append",
    "registerError": "logs://repository/errors/command/register",
}
EXPECTED_REQUEST_GBNF = "\n".join(
    (
        r"root ::= inspect | plan_append",
        r'inspect ::= "{\"schema\":\"wellmanifest.logs/request/v1\",\"operation\":\"inspect\",\"processRef\":\"logs://repository/contracts/query/inspect\"}"',
        r'plan_append ::= "{\"schema\":\"wellmanifest.logs/request/v1\",\"operation\":\"plan_append\",\"processRef\":\"logs://stream/events/query/plan-append\",\"stream\":" string ",\"expectedVersion\":" integer ",\"eventRef\":" string ",\"eventSha256\":" string "}"',
        r'integer ::= "0" | [1-9] [0-9]*',
        r'string ::= "\"" chars "\""',
        r'chars ::= ([^"\\\x00-\x1f] | "\\" (["\\/bfnrt] | "u" [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F] [0-9a-fA-F]))*',
    )
) + "\n"
CONTINUITY_EVENT_TYPES = (
    "agent.session_started",
    "agent.intent_compiled",
    "agent.tool_requested",
    "agent.tool_completed",
    "git.slice_checkpointed",
    "work.split_requested",
    "work.split_materialized",
    "git.commit_created",
    "git.push_started",
    "git.push_completed",
    "agent.resume_observed",
    "agent.resume_decided",
    "agent.snapshot_recorded",
)
CONTINUITY_SCHEMA_NAMES = {
    "agent.session_started": "sessionStarted",
    "agent.intent_compiled": "intentCompiled",
    "agent.tool_requested": "toolRequested",
    "agent.tool_completed": "toolCompleted",
    "git.slice_checkpointed": "sliceCheckpointed",
    "work.split_requested": "splitRequested",
    "work.split_materialized": "splitMaterialized",
    "git.commit_created": "commitCreated",
    "git.push_started": "pushStarted",
    "git.push_completed": "pushCompleted",
    "agent.resume_observed": "resumeObserved",
    "agent.resume_decided": "resumeDecided",
    "agent.snapshot_recorded": "snapshotRecorded",
}
CONTINUITY_FIELDS = {
    "agent.session_started": {"sessionDigest"},
    "agent.intent_compiled": {
        "sourceDigest",
        "intentDigest",
        "compilerReceiptRef",
    },
    "agent.tool_requested": {"intentDigest", "requestDigest"},
    "agent.tool_completed": {"requestDigest", "resultDigest", "executionReceiptRef"},
    "git.slice_checkpointed": {
        "sliceDigest",
        "validationDigests",
        "validationReceiptRefs",
    },
    "work.split_requested": {"parentWorkDigest", "splitPlanDigest"},
    "work.split_materialized": {
        "splitPlanDigest",
        "acceptedWorkDigests",
        "splitReceiptRef",
    },
    "git.commit_created": {"sliceDigest", "commitDigest", "commitReceiptRef"},
    "git.push_started": {"commitDigest", "pushPlanDigest", "pushStartReceiptRef"},
    "git.push_completed": {
        "commitDigest",
        "pushPlanDigest",
        "remoteStateDigest",
        "pushReceiptRef",
    },
    "agent.resume_observed": {
        "snapshotDigest",
        "expectedStateDigest",
        "observedStateDigest",
        "observationDigest",
        "observationReceiptRef",
    },
    "agent.resume_decided": {
        "observationDigest",
        "decisionDigest",
        "decisionReceiptRef",
    },
    "agent.snapshot_recorded": {"snapshotDigest", "stateDigest", "snapshotReceiptRef"},
}
CAUSAL_PARENT_TYPES = {
    "agent.intent_compiled": "agent.session_started",
    "agent.tool_requested": "agent.intent_compiled",
    "agent.tool_completed": "agent.tool_requested",
    "work.split_materialized": "work.split_requested",
    "git.commit_created": "git.slice_checkpointed",
    "git.push_started": "git.commit_created",
    "git.push_completed": "git.push_started",
    "agent.resume_observed": "agent.snapshot_recorded",
    "agent.resume_decided": "agent.resume_observed",
}
EXPECTED_PROTO_MESSAGES = (
    "EvidenceRef",
    "DiagnosticContext",
    "AgentSessionStarted",
    "AgentIntentCompiled",
    "AgentToolRequested",
    "AgentToolCompleted",
    "GitSliceCheckpointed",
    "WorkSplitRequested",
    "WorkSplitMaterialized",
    "GitCommitCreated",
    "GitPushStarted",
    "GitPushCompleted",
    "AgentResumeObserved",
    "AgentResumeDecided",
    "AgentSnapshotRecorded",
    "ContinuityPayload",
    "LogEvent",
    "ErrorDefinition",
    "InspectRequest",
    "InspectResponse",
    "PlanAppendRequest",
    "PlanAppendResponse",
    "ExecuteAppendRequest",
    "ExecuteAppendResponse",
    "ValidateRepositoryRequest",
    "ValidateRepositoryResponse",
    "ReadStreamRequest",
    "ReadStreamResponse",
    "Finding",
)
EXPECTED_RPCS = (
    "rpc Inspect(InspectRequest) returns (InspectResponse);",
    "rpc PlanAppend(PlanAppendRequest) returns (PlanAppendResponse);",
    "rpc ExecuteAppend(ExecuteAppendRequest) returns (ExecuteAppendResponse);",
    "rpc ValidateRepository(ValidateRepositoryRequest) returns (ValidateRepositoryResponse);",
    "rpc ReadStream(ReadStreamRequest) returns (ReadStreamResponse);",
)
EXPECTED_CONTINUITY_PROTO_FIELDS = (
    "string session_digest = 1;",
    "string source_digest = 1;",
    "string intent_digest = 2;",
    "string compiler_receipt_ref = 3;",
    "string intent_digest = 1;",
    "string request_digest = 2;",
    "string request_digest = 1;",
    "string execution_receipt_ref = 3;",
    "repeated string validation_digests = 2;",
    "repeated string validation_receipt_refs = 3;",
    "string parent_work_digest = 1;",
    "string split_plan_digest = 2;",
    "repeated string accepted_work_digests = 2;",
    "string split_receipt_ref = 3;",
    "string commit_receipt_ref = 3;",
    "string push_plan_digest = 2;",
    "string push_start_receipt_ref = 3;",
    "string remote_state_digest = 3;",
    "string push_receipt_ref = 4;",
    "string snapshot_digest = 1;",
    "string expected_state_digest = 2;",
    "string observed_state_digest = 3;",
    "string observation_digest = 4;",
    "string observation_receipt_ref = 5;",
    "string observation_digest = 1;",
    "string decision_digest = 2;",
    "string decision_receipt_ref = 3;",
    "string state_digest = 2;",
    "string snapshot_receipt_ref = 3;",
    "string slice_digest = 1;",
    "string commit_digest = 2;",
    "string commit_digest = 1;",
    "AgentSessionStarted agent_session_started = 1;",
    "AgentIntentCompiled agent_intent_compiled = 2;",
    "AgentToolRequested agent_tool_requested = 3;",
    "AgentToolCompleted agent_tool_completed = 4;",
    "GitSliceCheckpointed git_slice_checkpointed = 5;",
    "WorkSplitRequested work_split_requested = 6;",
    "WorkSplitMaterialized work_split_materialized = 7;",
    "GitCommitCreated git_commit_created = 8;",
    "GitPushStarted git_push_started = 9;",
    "GitPushCompleted git_push_completed = 10;",
    "AgentResumeObserved agent_resume_observed = 11;",
    "AgentResumeDecided agent_resume_decided = 12;",
    "AgentSnapshotRecorded agent_snapshot_recorded = 13;",
)


@dataclass(frozen=True)
class Finding:
    code: str
    rule: str
    severity: str
    path: str
    message: str
    helpPath: str = HELP_PATH


class ContractFailure(ValueError):
    def __init__(self, rule: str, path: str, message: str) -> None:
        super().__init__(message)
        self.rule = rule
        self.path = path
        self.message = message


def canonical(value: Any) -> str:
    """Canonical JSON for the v1 domain, which deliberately excludes floats."""
    _reject_float(value)
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _reject_float(value: Any) -> None:
    if isinstance(value, float):
        raise ContractFailure(
            "LOGS-CANONICAL-NUMBER",
            CONTRACT_PATH.as_posix(),
            "floating-point values are outside the v1 canonical domain",
        )
    if isinstance(value, dict):
        for child in value.values():
            _reject_float(child)
    elif isinstance(value, list):
        for child in value:
            _reject_float(child)


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def exact_fields(
    value: Any,
    required: set[str],
    *,
    rule: str,
    path: str,
) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractFailure(rule, path, "document must be an object")
    observed = set(value)
    if observed != required:
        raise ContractFailure(rule, path, "document fields do not match the closed contract")
    return value


def read_json(path: Path, *, rule: str, label: str) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractFailure(rule, path.as_posix(), f"{label} is unreadable or invalid") from error


def validate_adopted_event_schema(root: Path, candidate_path: Path) -> dict[str, Any]:
    """Compare an adopted event schema with the canonical semantic schema."""
    findings: list[Finding] = []
    contract_sha = ""
    candidate_sha = ""
    try:
        bundle, contract_sha = load_contract(root)
        try:
            size = candidate_path.stat().st_size
        except OSError as error:
            raise ContractFailure(
                "LOGS-ADOPTION-SCHEMA-READ",
                candidate_path.as_posix(),
                "adopted event schema is unavailable",
            ) from error
        if size < 2 or size > MAX_ADOPTED_SCHEMA_BYTES:
            raise ContractFailure(
                "LOGS-ADOPTION-SCHEMA-SIZE",
                candidate_path.as_posix(),
                "adopted event schema exceeds the bounded input size",
            )
        candidate = read_json(
            candidate_path,
            rule="LOGS-ADOPTION-SCHEMA-JSON",
            label="adopted event schema",
        )
        candidate_canonical = canonical(candidate)
        candidate_sha = sha256_bytes(candidate_canonical.encode("utf-8"))
        if candidate_canonical != canonical(bundle["schemas"]["event"]):
            raise ContractFailure(
                "LOGS-ADOPTION-SCHEMA-DRIFT",
                candidate_path.as_posix(),
                "adopted event schema differs from the canonical contract; update the vendored schema or declare a separately versioned projection",
            )
    except ContractFailure as error:
        findings.append(finding(error))
    return {
        "schema": "wellmanifest.logs/adoption-report/v1",
        "valid": not findings,
        "contractSha256": contract_sha,
        "candidateSchemaSha256": candidate_sha,
        "findings": [asdict(item) for item in findings],
    }


def validate_adopted_error_catalog(root: Path, catalog_path: Path) -> dict[str, Any]:
    """Validate one adopter-owned, contract-pinned error catalog and runbook set."""
    findings: list[Finding] = []
    contract_sha = ""
    catalog_sha = ""
    errors_checked = 0
    try:
        bundle, contract_sha = load_contract(root)
        try:
            size = catalog_path.stat().st_size
        except OSError as error:
            raise ContractFailure(
                "LOGS-ADOPTION-ERROR-CATALOG-READ",
                catalog_path.as_posix(),
                "adopter error catalog is unavailable",
            ) from error
        if catalog_path.is_symlink() or size < 2 or size > MAX_ADOPTED_CATALOG_BYTES:
            raise ContractFailure(
                "LOGS-ADOPTION-ERROR-CATALOG-SIZE",
                catalog_path.as_posix(),
                "adopter error catalog is not a bounded regular file",
            )
        catalog_sha = sha256_file(catalog_path)
        catalog = exact_fields(
            read_json(
                catalog_path,
                rule="LOGS-ADOPTION-ERROR-CATALOG-JSON",
                label="adopter error catalog",
            ),
            {"schema", "namespace", "contractSha256", "errorsDirectory", "diagnosticCodes"},
            rule="LOGS-ADOPTION-ERROR-CATALOG-FIELDS",
            path=catalog_path.as_posix(),
        )
        if catalog.get("schema") != "wellmanifest.logs/adopter-error-catalog/v1":
            raise ContractFailure(
                "LOGS-ADOPTION-ERROR-CATALOG-SCHEMA",
                catalog_path.as_posix(),
                "adopter error catalog schema is unsupported",
            )
        namespace = catalog.get("namespace")
        reserved_namespaces = bundle["vocabulary"]["reservedErrorNamespaces"]
        if (
            not isinstance(namespace, str)
            or NAMESPACE_RE.fullmatch(namespace) is None
            or namespace in reserved_namespaces
        ):
            raise ContractFailure(
                "LOGS-ADOPTION-ERROR-NAMESPACE",
                catalog_path.as_posix(),
                "adopter namespace is invalid or reserved by wellmanifest/logs",
            )
        if catalog.get("contractSha256") != contract_sha:
            raise ContractFailure(
                "LOGS-ADOPTION-ERROR-CONTRACT-DRIFT",
                catalog_path.as_posix(),
                "adopter catalog is not pinned to the canonical contract digest",
            )
        errors_directory = catalog.get("errorsDirectory")
        if not isinstance(errors_directory, str) or PATH_RE.fullmatch(errors_directory) is None:
            raise ContractFailure(
                "LOGS-ADOPTION-ERROR-PATH",
                catalog_path.as_posix(),
                "adopter errors directory violates repository confinement",
            )
        codes = require_string_list(
            catalog.get("diagnosticCodes"),
            minimum=1,
            maximum=256,
            unique=True,
            rule="LOGS-ADOPTION-ERROR-CODES",
            path=catalog_path.as_posix(),
        )
        if codes != sorted(codes) or any(
            CODE_RE.fullmatch(code) is None or not code.startswith(f"{namespace}-")
            for code in codes
        ):
            raise ContractFailure(
                "LOGS-ADOPTION-ERROR-NAMESPACE",
                catalog_path.as_posix(),
                "diagnostic codes must be sorted stable codes owned by the declared namespace",
            )
        documents = load_error_documents(
            catalog_path.parent,
            bundle,
            directory_relative=errors_directory,
            declared=set(codes),
        )
        errors_checked = len(documents)
    except ContractFailure as error:
        findings.append(finding(error))
    return {
        "schema": "wellmanifest.logs/error-adoption-report/v1",
        "valid": not findings,
        "contractSha256": contract_sha,
        "candidateCatalogSha256": catalog_sha,
        "errorDefinitionsChecked": errors_checked,
        "findings": [asdict(item) for item in findings],
    }


def _assert_closed_objects(value: Any, path: str = "schemas") -> None:
    if isinstance(value, dict):
        if value.get("type") == "object" and value.get("additionalProperties") is not False:
            raise ContractFailure(
                "LOGS-CONTRACT-CLOSED",
                CONTRACT_PATH.as_posix(),
                f"object schema at {path} is not closed",
            )
        for key, child in value.items():
            _assert_closed_objects(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _assert_closed_objects(child, f"{path}[{index}]")


def load_contract(root: Path) -> tuple[dict[str, Any], str]:
    path = root / CONTRACT_PATH
    bundle = exact_fields(
        read_json(path, rule="LOGS-CONTRACT-JSON", label="contract bundle"),
        {
            "$schema",
            "schema",
            "version",
            "canonical",
            "protobufPath",
            "projection",
            "hashProfile",
            "processes",
            "diagnosticCodes",
            "vocabulary",
            "requestGbnf",
            "schemas",
        },
        rule="LOGS-CONTRACT-FIELDS",
        path=CONTRACT_PATH.as_posix(),
    )
    constants = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "schema": "wellmanifest.logs/contract-bundle/v1",
        "version": "0.5.0",
        "canonical": "protobuf",
        "protobufPath": "proto/v0.5/wellmanifest/logs/v1/logs.proto",
        "projection": "canonical-jsonl",
        "hashProfile": "wellmanifest-canonical-json-v1+SHA-256",
    }
    if any(bundle.get(key) != expected for key, expected in constants.items()):
        raise ContractFailure(
            "LOGS-CONTRACT-IDENTITY",
            CONTRACT_PATH.as_posix(),
            "contract identity or canonicalization profile changed",
        )
    if bundle.get("processes") != EXPECTED_PROCESSES:
        raise ContractFailure(
            "LOGS-CONTRACT-PROCESS",
            CONTRACT_PATH.as_posix(),
            "POA process registry is incomplete or changed",
        )
    if bundle.get("diagnosticCodes") != [DIAGNOSTIC_CODE]:
        raise ContractFailure(
            "LOGS-CONTRACT-CATALOG",
            CONTRACT_PATH.as_posix(),
            "diagnostic catalog does not match the v1 runtime",
        )
    schemas = exact_fields(
        bundle.get("schemas"),
        {"evidence", "event", "error", "request"},
        rule="LOGS-CONTRACT-SCHEMAS",
        path=CONTRACT_PATH.as_posix(),
    )
    vocabulary = exact_fields(
        bundle.get("vocabulary"),
        {
            "severities",
            "eventTypes",
            "continuityEventTypes",
            "outcomes",
            "errorCategories",
            "reservedErrorNamespaces",
            "modes",
        },
        rule="LOGS-CONTRACT-VOCABULARY",
        path=CONTRACT_PATH.as_posix(),
    )
    for key in vocabulary:
        values = vocabulary[key]
        if not isinstance(values, list) or not values or len(values) != len(set(values)):
            raise ContractFailure(
                "LOGS-CONTRACT-VOCABULARY",
                CONTRACT_PATH.as_posix(),
                "contract vocabulary must contain nonempty unique arrays",
            )
    if vocabulary["errorCategories"] != sorted(vocabulary["errorCategories"]) or any(
        NAMESPACE_RE.fullmatch(item) is None
        for item in vocabulary["reservedErrorNamespaces"]
    ):
        raise ContractFailure(
            "LOGS-CONTRACT-VOCABULARY",
            CONTRACT_PATH.as_posix(),
            "unordered categories or invalid reserved error namespaces",
        )
    if vocabulary["continuityEventTypes"] != list(CONTINUITY_EVENT_TYPES):
        raise ContractFailure(
            "LOGS-CONTRACT-CONTINUITY",
            CONTRACT_PATH.as_posix(),
            "continuity event vocabulary is incomplete or reordered",
        )
    event_properties = schemas["event"].get("properties", {})
    if event_properties.get("severity", {}).get("enum") != vocabulary["severities"]:
        raise ContractFailure(
            "LOGS-CONTRACT-VOCABULARY",
            CONTRACT_PATH.as_posix(),
            "event severity schema differs from vocabulary",
        )
    # eventType is an open union: the reserved core enum plus a namespaced
    # deployment pattern. Only the reserved half is vocabulary-controlled.
    event_type_union = event_properties.get("eventType", {}).get("oneOf")
    if (
        not isinstance(event_type_union, list)
        or len(event_type_union) != 2
        or event_type_union[0].get("enum") != vocabulary["eventTypes"]
        or event_type_union[1].get("pattern") != DOMAIN_TYPE_RE.pattern
    ):
        raise ContractFailure(
            "LOGS-CONTRACT-VOCABULARY",
            CONTRACT_PATH.as_posix(),
            "event type schema differs from vocabulary",
        )
    if event_properties.get("mode", {}).get("enum") != vocabulary["modes"]:
        raise ContractFailure(
            "LOGS-CONTRACT-VOCABULARY",
            CONTRACT_PATH.as_posix(),
            "event mode schema differs from vocabulary",
        )
    if event_properties.get("outcome", {}).get("enum") != vocabulary["outcomes"]:
        raise ContractFailure(
            "LOGS-CONTRACT-VOCABULARY",
            CONTRACT_PATH.as_posix(),
            "event outcome schema differs from vocabulary",
        )
    diagnostic_fields = {
        "phase",
        "status",
        "retryable",
        "attempt",
        "attempts",
        "durationMs",
        "endpointRef",
        "transportCode",
        "httpStatus",
        "remediationRefs",
        "traceId",
        "spanId",
    }
    diagnostic_schema = schemas["event"].get("$defs", {}).get("diagnostic", {})
    if (
        "diagnostic" in schemas["event"].get("required", [])
        or event_properties.get("diagnostic") != {"$ref": "#/$defs/diagnostic"}
        or set(diagnostic_schema.get("required", [])) != diagnostic_fields
        or set(diagnostic_schema.get("properties", {})) != diagnostic_fields
    ):
        raise ContractFailure(
            "LOGS-CONTRACT-DIAGNOSTIC",
            CONTRACT_PATH.as_posix(),
            "optional operational diagnostic schema is incomplete or no longer closed",
        )
    event_definitions = schemas["event"].get("$defs", {})
    continuity_property = event_properties.get("continuity", {})
    continuity_refs = continuity_property.get("oneOf")
    expected_refs = [
        {"$ref": f"#/$defs/{CONTINUITY_SCHEMA_NAMES[event_type]}"}
        for event_type in CONTINUITY_EVENT_TYPES
    ]
    if (
        "continuity" in schemas["event"].get("required", [])
        or continuity_refs != expected_refs
        or any(
            set(event_definitions.get(CONTINUITY_SCHEMA_NAMES[event_type], {}).get("required", []))
            != fields
            or set(
                event_definitions.get(CONTINUITY_SCHEMA_NAMES[event_type], {}).get(
                    "properties", {}
                )
            )
            != fields
            for event_type, fields in CONTINUITY_FIELDS.items()
        )
    ):
        raise ContractFailure(
            "LOGS-CONTRACT-CONTINUITY",
            CONTRACT_PATH.as_posix(),
            "continuity payload variants are incomplete or no longer closed",
        )
    continuity_conditions = schemas["event"].get("allOf")
    conditioned_types = []
    if isinstance(continuity_conditions, list):
        for condition in continuity_conditions:
            event_type_schema = condition.get("if", {}).get("properties", {}).get(
                "eventType", {}
            )
            if "const" in event_type_schema:
                conditioned_types.append(event_type_schema["const"])
    if conditioned_types != list(CONTINUITY_EVENT_TYPES):
        raise ContractFailure(
            "LOGS-CONTRACT-CONTINUITY",
            CONTRACT_PATH.as_posix(),
            "continuity event-to-payload conditions are incomplete or reordered",
        )
    error_properties = schemas["error"].get("properties", {})
    if error_properties.get("category", {}).get("enum") != vocabulary["errorCategories"]:
        raise ContractFailure(
            "LOGS-CONTRACT-VOCABULARY",
            CONTRACT_PATH.as_posix(),
            "error category schema differs from vocabulary",
        )
    _assert_closed_objects(schemas)
    if bundle.get("requestGbnf") != EXPECTED_REQUEST_GBNF:
        raise ContractFailure(
            "LOGS-CONTRACT-GRAMMAR",
            CONTRACT_PATH.as_posix(),
            "request grammar differs from the closed propose-only compatibility unit",
        )
    return bundle, sha256_file(path)


def validate_proto(root: Path, bundle: dict[str, Any]) -> None:
    relative = Path(bundle["protobufPath"])
    path = confined_file(root, relative.as_posix(), "LOGS-PROTO-PATH")
    try:
        text = path.read_text("utf-8")
    except (OSError, UnicodeError) as error:
        raise ContractFailure(
            "LOGS-PROTO-READ",
            relative.as_posix(),
            "Protobuf contract is unreadable",
        ) from error
    required = [
        'syntax = "proto3";',
        "package wellmanifest.logs.v1;",
        "service LogsControlService {",
        "oneof event {",
        "optional ContinuityPayload continuity = 25;",
        *(f"message {name} {{" for name in EXPECTED_PROTO_MESSAGES),
        *EXPECTED_CONTINUITY_PROTO_FIELDS,
        *EXPECTED_RPCS,
    ]
    vocabulary = bundle["vocabulary"]
    required.extend(f"SEVERITY_{value}" for value in vocabulary["severities"])
    required.extend(
        f"EVENT_TYPE_{value.upper()}" for value in vocabulary["eventTypes"]
    )
    required.extend(f"OUTCOME_{value}" for value in vocabulary["outcomes"])
    required.extend(f"MODE_{value}" for value in vocabulary["modes"])
    forbidden = (
        "google.protobuf.Struct",
        "google.protobuf.Value",
        "bytes payload",
        "string raw_output",
        "string credential",
        "string shell",
    )
    if any(fragment not in text for fragment in required) or any(
        fragment in text for fragment in forbidden
    ):
        raise ContractFailure(
            "LOGS-PROTO-COMPLETE",
            relative.as_posix(),
            "Protobuf messages, RPCs or bounded vocabulary are incomplete",
        )


def confined_file(root: Path, relative: str, rule: str) -> Path:
    if PATH_RE.fullmatch(relative) is None:
        raise ContractFailure(rule, relative, "path violates repository confinement")
    resolved_root = root.resolve()
    candidate = (resolved_root / relative).resolve()
    try:
        candidate.relative_to(resolved_root)
    except ValueError as error:
        raise ContractFailure(rule, relative, "path escapes the repository root") from error
    if not candidate.is_file():
        raise ContractFailure(rule, relative, "required file is missing")
    return candidate


def require_string_list(
    value: Any,
    *,
    minimum: int,
    maximum: int,
    unique: bool,
    rule: str,
    path: str,
) -> list[str]:
    if (
        not isinstance(value, list)
        or not minimum <= len(value) <= maximum
        or any(not isinstance(item, str) or not item or len(item) > 320 for item in value)
        or (unique and len(value) != len(set(value)))
    ):
        raise ContractFailure(rule, path, "string list violates its bounded contract")
    return value


def validate_error_definition(
    value: Any,
    *,
    code: str,
    bundle: dict[str, Any],
    path: str,
) -> dict[str, Any]:
    definition = exact_fields(
        value,
        {
            "schema",
            "code",
            "version",
            "severity",
            "category",
            "title",
            "meaning",
            "causes",
            "remediation",
            "verification",
            "doNot",
            "owner",
            "relatedEventTypes",
        },
        rule="LOGS-DOC-FIELDS",
        path=path,
    )
    vocabulary = bundle["vocabulary"]
    if definition.get("schema") != "wellmanifest.logs/error/v1":
        raise ContractFailure("LOGS-DOC-SCHEMA", path, "error DSL schema is unsupported")
    if definition.get("code") != code or CODE_RE.fullmatch(code) is None:
        raise ContractFailure("LOGS-DOC-CODE", path, "error DSL code differs from its file")
    version = definition.get("version")
    if isinstance(version, bool) or not isinstance(version, int) or not 1 <= version <= 2147483647:
        raise ContractFailure("LOGS-DOC-VERSION", path, "error DSL version is invalid")
    allowed_severities = bundle["schemas"]["error"]["properties"]["severity"]["enum"]
    if definition.get("severity") not in allowed_severities:
        raise ContractFailure("LOGS-DOC-SEVERITY", path, "error severity is invalid")
    if definition.get("category") not in vocabulary["errorCategories"]:
        raise ContractFailure("LOGS-DOC-CATEGORY", path, "error category is invalid")
    for key, maximum in (("title", 160), ("meaning", 600)):
        item = definition.get(key)
        if not isinstance(item, str) or not item or len(item) > maximum:
            raise ContractFailure("LOGS-DOC-TEXT", path, f"error {key} is invalid")
    require_string_list(
        definition.get("causes"),
        minimum=1,
        maximum=12,
        unique=True,
        rule="LOGS-DOC-CAUSES",
        path=path,
    )
    for key in ("remediation", "verification", "doNot"):
        require_string_list(
            definition.get(key),
            minimum=1,
            maximum=12,
            unique=False,
            rule="LOGS-DOC-STEPS",
            path=path,
        )
    owner = definition.get("owner")
    if not isinstance(owner, str) or OWNER_RE.fullmatch(owner) is None:
        raise ContractFailure("LOGS-DOC-OWNER", path, "error owner route is invalid")
    related = require_string_list(
        definition.get("relatedEventTypes"),
        minimum=1,
        maximum=7,
        unique=True,
        rule="LOGS-DOC-EVENTS",
        path=path,
    )
    if any(item not in vocabulary["eventTypes"] for item in related):
        raise ContractFailure("LOGS-DOC-EVENTS", path, "error references an unknown event type")
    return definition


def load_error_documents(
    root: Path,
    bundle: dict[str, Any],
    *,
    directory_relative: str,
    declared: set[str],
) -> dict[str, dict[str, Any]]:
    resolved_root = root.resolve()
    unresolved_directory = resolved_root / directory_relative
    directory = unresolved_directory.resolve()
    try:
        directory.relative_to(resolved_root)
    except ValueError as error:
        raise ContractFailure(
            "LOGS-DOC-DIRECTORY",
            directory_relative,
            "error directory escapes its catalog root",
        ) from error
    if unresolved_directory.is_symlink() or not directory.is_dir():
        raise ContractFailure(
            "LOGS-DOC-DIRECTORY",
            directory_relative,
            "error directory is missing or symbolic",
        )
    documents: dict[str, dict[str, Any]] = {}
    unexpected = sorted(
        item.name for item in directory.iterdir() if not item.is_file() or item.suffix != ".md"
    )
    if unexpected:
        raise ContractFailure(
            "LOGS-DOC-PATH",
            directory_relative,
            "error directory contains an unsupported entry",
        )
    fence_pattern = re.compile(r"```log-error-dsl\n([^\n]+)\n```", re.MULTILINE)
    for file_path in sorted(directory.glob("*.md")):
        code = file_path.stem
        relative = file_path.relative_to(resolved_root).as_posix()
        if CODE_RE.fullmatch(code) is None:
            raise ContractFailure("LOGS-DOC-PATH", relative, "error filename is not a stable code")
        try:
            if file_path.is_symlink() or file_path.stat().st_size > MAX_ERROR_DOCUMENT_BYTES:
                raise OSError("error page is symbolic or exceeds the bounded size")
            text = file_path.read_text("utf-8")
        except (OSError, UnicodeError) as error:
            raise ContractFailure("LOGS-DOC-READ", relative, "error page is unreadable") from error
        for section in REQUIRED_ERROR_SECTIONS:
            marker = f"## {section}\n"
            if text.count(marker) != 1:
                raise ContractFailure(
                    "LOGS-DOC-SECTIONS",
                    relative,
                    "error page does not contain each required section exactly once",
                )
            after = text.split(marker, 1)[1]
            body = after.split("\n## ", 1)[0].strip()
            if not body:
                raise ContractFailure(
                    "LOGS-DOC-SECTIONS",
                    relative,
                    "error page contains an empty required section",
                )
        fences = fence_pattern.findall(text)
        if len(fences) != 1:
            raise ContractFailure(
                "LOGS-DOC-FENCE",
                relative,
                "error page must contain exactly one single-line log-error-dsl fence",
            )
        try:
            definition = json.loads(fences[0])
        except json.JSONDecodeError as error:
            raise ContractFailure("LOGS-DOC-JSON", relative, "embedded error DSL is invalid") from error
        if canonical(definition) != fences[0]:
            raise ContractFailure("LOGS-DOC-CANONICAL", relative, "embedded error DSL is not canonical")
        documents[code] = validate_error_definition(
            definition,
            code=code,
            bundle=bundle,
            path=relative,
        )
        expected_title = f"# {code}: {documents[code]['title']}\n"
        if not text.startswith(expected_title):
            raise ContractFailure(
                "LOGS-DOC-TITLE",
                relative,
                "error heading does not match its filename and embedded DSL title",
            )
    if set(documents) != declared:
        raise ContractFailure(
            "LOGS-DOC-CATALOG",
            directory_relative,
            "error page set differs from the diagnostic catalog",
        )
    return documents


def load_error_catalog(root: Path, bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return load_error_documents(
        root,
        bundle,
        directory_relative="errors",
        declared=set(bundle["diagnosticCodes"]),
    )


def require_datetime(value: Any, path: str) -> None:
    if not isinstance(value, str) or DATETIME_RE.fullmatch(value) is None:
        raise ContractFailure("LOGS-EVENT-TIME", path, "event time is not normalized UTC")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as error:
        raise ContractFailure("LOGS-EVENT-TIME", path, "event time is invalid") from error
    if parsed.utcoffset() is None:
        raise ContractFailure("LOGS-EVENT-TIME", path, "event time has no timezone")


def calculate_event_hash(event: dict[str, Any]) -> str:
    payload = {key: copy.deepcopy(value) for key, value in event.items() if key != "eventHash"}
    return sha256_bytes(canonical(payload).encode("utf-8"))


def validate_continuity(
    event: dict[str, Any],
    *,
    prior_events: dict[str, dict[str, Any]],
    path: str,
) -> None:
    event_type = event["eventType"]
    if event_type not in CONTINUITY_EVENT_TYPES:
        if "continuity" in event:
            raise ContractFailure(
                "LOGS-EVENT-CONTINUITY",
                path,
                "continuity payload is only valid for a declared continuity event type",
            )
        return
    if "continuity" not in event:
        raise ContractFailure(
            "LOGS-EVENT-CONTINUITY",
            path,
            "declared continuity event is missing its typed payload",
        )
    payload = exact_fields(
        event["continuity"],
        CONTINUITY_FIELDS[event_type],
        rule="LOGS-EVENT-CONTINUITY",
        path=path,
    )
    for name, item in payload.items():
        if name.endswith("Digests"):
            minimum = 2 if name == "acceptedWorkDigests" else 1
            if (
                not isinstance(item, list)
                or not minimum <= len(item) <= 16
                or len(item) != len(set(item))
                or any(not isinstance(value, str) or SHA_RE.fullmatch(value) is None for value in item)
            ):
                raise ContractFailure(
                    "LOGS-EVENT-CONTINUITY",
                    path,
                    "continuity digest list is invalid",
                )
        elif name.endswith("ReceiptRefs"):
            if (
                not isinstance(item, list)
                or not 1 <= len(item) <= 16
                or len(item) != len(set(item))
                or any(
                    not isinstance(value, str)
                    or len(value) > 160
                    or RECEIPT_RE.fullmatch(value) is None
                    for value in item
                )
            ):
                raise ContractFailure(
                    "LOGS-EVENT-CONTINUITY",
                    path,
                    "continuity receipt reference list is invalid",
                )
        elif name.endswith("ReceiptRef"):
            if (
                not isinstance(item, str)
                or len(item) > 160
                or RECEIPT_RE.fullmatch(item) is None
            ):
                raise ContractFailure(
                    "LOGS-EVENT-CONTINUITY",
                    path,
                    "continuity receipt reference is invalid",
                )
        elif not isinstance(item, str) or SHA_RE.fullmatch(item) is None:
            raise ContractFailure(
                "LOGS-EVENT-CONTINUITY",
                path,
                "continuity digest is invalid",
            )

    causation = event["causationId"]
    if event_type == "agent.session_started":
        if causation is not None:
            raise ContractFailure(
                "LOGS-EVENT-CONTINUITY-CAUSE",
                path,
                "a session start must be the continuity correlation root",
            )
        return
    cause = prior_events.get(causation) if isinstance(causation, str) else None
    if cause is None or cause.get("correlationId") != event["correlationId"]:
        raise ContractFailure(
            "LOGS-EVENT-CONTINUITY-CAUSE",
            path,
            "continuity causation must reference a prior event in the same correlation",
        )
    expected_parent_type = CAUSAL_PARENT_TYPES.get(event_type)
    if expected_parent_type is not None and cause.get("eventType") != expected_parent_type:
        raise ContractFailure(
            "LOGS-EVENT-CONTINUITY-CAUSE",
            path,
            "continuity event references the wrong causal event type",
        )
    cause_payload = cause.get("continuity", {})
    paired_digest_fields = {
        "agent.tool_requested": ("intentDigest",),
        "agent.tool_completed": ("requestDigest",),
        "work.split_materialized": ("splitPlanDigest",),
        "git.commit_created": ("sliceDigest",),
        "git.push_started": ("commitDigest",),
        "git.push_completed": ("commitDigest", "pushPlanDigest"),
        "agent.resume_decided": ("observationDigest",),
    }
    paired_fields = paired_digest_fields.get(event_type, ())
    if any(payload[field] != cause_payload.get(field) for field in paired_fields):
        raise ContractFailure(
            "LOGS-EVENT-CONTINUITY-DIGEST",
            path,
            "continuity event digest differs from its causal boundary",
        )
    if event_type == "agent.resume_observed" and (
        payload["snapshotDigest"] != cause_payload.get("snapshotDigest")
        or payload["expectedStateDigest"] != cause_payload.get("stateDigest")
    ):
        raise ContractFailure(
            "LOGS-EVENT-CONTINUITY-DIGEST",
            path,
            "resume observation does not match its recorded snapshot",
        )
    if event_type == "agent.resume_decided":
        diverged = cause_payload.get("observedStateDigest") != cause_payload.get(
            "expectedStateDigest"
        )
        expected_outcome = "REJECTED" if diverged else "ACCEPTED"
        expected_state = "diverged" if diverged else "resume"
        if (
            event.get("outcome") != expected_outcome
            or event.get("subjectState") != expected_state
        ):
            raise ContractFailure(
                "LOGS-EVENT-CONTINUITY-DECISION",
                path,
                "resume decision does not match the observed snapshot state",
            )


def validate_event(
    event: Any,
    *,
    bundle: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
    root: Path,
    path: str,
    stream: str,
    sequence: int,
    previous_hash: str,
    prior_events: dict[str, dict[str, Any]],
) -> str:
    event_schema = bundle["schemas"]["event"]
    required = set(event_schema["required"])
    allowed = set(event_schema["properties"])
    if not isinstance(event, dict):
        raise ContractFailure("LOGS-EVENT-FIELDS", path, "document must be an object")
    observed = set(event)
    if not required.issubset(observed) or not observed.issubset(allowed):
        raise ContractFailure(
            "LOGS-EVENT-FIELDS",
            path,
            "document fields do not match the closed contract",
        )
    value = event
    if value.get("schema") != "wellmanifest.logs/event/v1":
        raise ContractFailure("LOGS-EVENT-SCHEMA", path, "event schema is unsupported")
    if not isinstance(value.get("eventId"), str) or EVENT_ID_RE.fullmatch(value["eventId"]) is None:
        raise ContractFailure("LOGS-EVENT-ID", path, "event ID is invalid")
    if value.get("stream") != stream or STREAM_RE.fullmatch(stream) is None:
        raise ContractFailure("LOGS-EVENT-STREAM", path, "event stream differs from its file")
    observed_sequence = value.get("sequence")
    if (
        isinstance(observed_sequence, bool)
        or not isinstance(observed_sequence, int)
        or observed_sequence != sequence
    ):
        raise ContractFailure("LOGS-EVENT-SEQUENCE", path, "event sequence is not contiguous")
    vocabulary = bundle["vocabulary"]
    event_type = value.get("eventType")
    if event_type not in vocabulary["eventTypes"] and (
        not isinstance(event_type, str)
        or not 3 <= len(event_type) <= 64
        or DOMAIN_TYPE_RE.fullmatch(event_type) is None
    ):
        raise ContractFailure("LOGS-EVENT-TYPE", path, "event type is invalid")
    if value.get("severity") not in vocabulary["severities"]:
        raise ContractFailure("LOGS-EVENT-SEVERITY", path, "event severity is invalid")
    if value.get("mode") not in vocabulary["modes"]:
        raise ContractFailure("LOGS-EVENT-MODE", path, "event mode is invalid")
    if value.get("outcome") not in vocabulary["outcomes"]:
        raise ContractFailure("LOGS-EVENT-OUTCOME", path, "event outcome is invalid")
    subject_state = value.get("subjectState")
    if subject_state is not None and (
        not isinstance(subject_state, str)
        or len(subject_state) > 32
        or STATE_RE.fullmatch(subject_state) is None
    ):
        raise ContractFailure("LOGS-EVENT-STATE", path, "event subject state is invalid")
    require_datetime(value.get("occurredAt"), path)
    correlation = value.get("correlationId")
    causation = value.get("causationId")
    if not isinstance(correlation, str) or ID_RE.fullmatch(correlation) is None:
        raise ContractFailure("LOGS-EVENT-CORRELATION", path, "correlation ID is invalid")
    if causation is not None and (
        not isinstance(causation, str) or ID_RE.fullmatch(causation) is None
    ):
        raise ContractFailure("LOGS-EVENT-CAUSATION", path, "causation ID is invalid")
    producer = value.get("producer")
    source = value.get("source")
    subject = value.get("subjectRef")
    if (
        not isinstance(producer, str)
        or len(producer) > 128
        or ACTOR_RE.fullmatch(producer) is None
    ):
        raise ContractFailure("LOGS-EVENT-PRODUCER", path, "event producer is invalid")
    # Who acted and which subsystem emitted the record are separate dimensions;
    # collapsing them loses the ability to attribute an event to either one.
    if (
        not isinstance(source, str)
        or not 3 <= len(source) <= 64
        or SOURCE_RE.fullmatch(source) is None
    ):
        raise ContractFailure("LOGS-EVENT-SOURCE", path, "event source is invalid")
    if (
        not isinstance(subject, str)
        or len(subject) > 160
        or SUBJECT_RE.fullmatch(subject) is None
    ):
        raise ContractFailure("LOGS-EVENT-SUBJECT", path, "event subject is invalid")
    code = value.get("code")
    if code is not None and (not isinstance(code, str) or code not in catalog):
        raise ContractFailure("LOGS-EVENT-CODE", path, "event code has no error definition")
    if value.get("rawOutputIncluded") is not False or value.get("secretMaterialIncluded") is not False:
        raise ContractFailure("LOGS-EVENT-SAFETY", path, "event safety flags must both be false")
    input_hash = value.get("inputHash")
    if not isinstance(input_hash, str) or SHA_RE.fullmatch(input_hash) is None:
        raise ContractFailure("LOGS-EVENT-INPUT", path, "event input hash is invalid")
    receipt = value.get("receiptRef")
    # An absent receipt is null. A placeholder string would make an unexecuted
    # event indistinguishable from an executed one.
    if receipt is not None and (
        not isinstance(receipt, str)
        or len(receipt) > 160
        or RECEIPT_RE.fullmatch(receipt) is None
    ):
        raise ContractFailure("LOGS-EVENT-RECEIPT", path, "event receipt reference is invalid")
    validate_continuity(value, prior_events=prior_events, path=path)
    diagnostic = value.get("diagnostic")
    if diagnostic is not None:
        validate_diagnostic(diagnostic, path)
    evidence = value.get("evidence")
    # File evidence is optional because inputHash already binds the command
    # input; high-frequency domain events produce no artefact to reference.
    if not isinstance(evidence, list) or len(evidence) > 16:
        raise ContractFailure("LOGS-EVENT-EVIDENCE", path, "event evidence list is invalid")
    seen_evidence: set[tuple[str, str]] = set()
    for item in evidence:
        evidence_item = exact_fields(
            item,
            {"path", "sha256"},
            rule="LOGS-EVENT-EVIDENCE",
            path=path,
        )
        evidence_path = evidence_item.get("path")
        evidence_sha = evidence_item.get("sha256")
        if (
            not isinstance(evidence_path, str)
            or len(evidence_path) > 240
            or not isinstance(evidence_sha, str)
        ):
            raise ContractFailure("LOGS-EVENT-EVIDENCE", path, "event evidence entry is invalid")
        file_path = confined_file(root, evidence_path, "LOGS-EVENT-EVIDENCE")
        if SHA_RE.fullmatch(evidence_sha) is None or sha256_file(file_path) != evidence_sha:
            raise ContractFailure("LOGS-EVENT-EVIDENCE", path, "event evidence digest differs")
        pair = (evidence_path, evidence_sha)
        if pair in seen_evidence:
            raise ContractFailure("LOGS-EVENT-EVIDENCE", path, "event evidence is duplicated")
        seen_evidence.add(pair)
    if value.get("previousHash") != previous_hash:
        raise ContractFailure("LOGS-EVENT-CHAIN", path, "event predecessor hash is invalid")
    event_hash = value.get("eventHash")
    if not isinstance(event_hash, str) or SHA_RE.fullmatch(event_hash) is None:
        raise ContractFailure("LOGS-EVENT-HASH", path, "event hash format is invalid")
    if calculate_event_hash(value) != event_hash:
        raise ContractFailure("LOGS-EVENT-HASH", path, "event hash differs from canonical bytes")
    return event_hash


def validate_diagnostic(value: Any, path: str) -> None:
    fields = {
        "phase",
        "status",
        "retryable",
        "attempt",
        "attempts",
        "durationMs",
        "endpointRef",
        "transportCode",
        "httpStatus",
        "remediationRefs",
        "traceId",
        "spanId",
    }
    diagnostic = exact_fields(
        value,
        fields,
        rule="LOGS-EVENT-DIAGNOSTIC",
        path=path,
    )
    for name in ("phase", "status"):
        item = diagnostic.get(name)
        if (
            not isinstance(item, str)
            or len(item) > 32
            or STATE_RE.fullmatch(item) is None
        ):
            raise ContractFailure(
                "LOGS-EVENT-DIAGNOSTIC", path, f"diagnostic {name} is invalid"
            )
    if not isinstance(diagnostic.get("retryable"), bool):
        raise ContractFailure(
            "LOGS-EVENT-DIAGNOSTIC", path, "diagnostic retryability is invalid"
        )
    attempt = diagnostic.get("attempt")
    attempts = diagnostic.get("attempts")
    if (
        isinstance(attempt, bool)
        or not isinstance(attempt, int)
        or isinstance(attempts, bool)
        or not isinstance(attempts, int)
        or not 1 <= attempt <= attempts <= 1000
    ):
        raise ContractFailure(
            "LOGS-EVENT-DIAGNOSTIC", path, "diagnostic attempt counters are invalid"
        )
    duration = diagnostic.get("durationMs")
    if (
        isinstance(duration, bool)
        or not isinstance(duration, int)
        or not 0 <= duration <= 604800000
    ):
        raise ContractFailure(
            "LOGS-EVENT-DIAGNOSTIC", path, "diagnostic duration is invalid"
        )
    endpoint = diagnostic.get("endpointRef")
    if endpoint is not None and (
        not isinstance(endpoint, str)
        or len(endpoint) > 255
        or ENDPOINT_REF_RE.fullmatch(endpoint) is None
    ):
        raise ContractFailure(
            "LOGS-EVENT-DIAGNOSTIC",
            path,
            "endpoint reference is not a secret-free origin or opaque reference",
        )
    transport = diagnostic.get("transportCode")
    if transport is not None and (
        not isinstance(transport, str)
        or TRANSPORT_CODE_RE.fullmatch(transport) is None
    ):
        raise ContractFailure(
            "LOGS-EVENT-DIAGNOSTIC", path, "diagnostic transport code is invalid"
        )
    http_status = diagnostic.get("httpStatus")
    if http_status is not None and (
        isinstance(http_status, bool)
        or not isinstance(http_status, int)
        or not 100 <= http_status <= 599
    ):
        raise ContractFailure(
            "LOGS-EVENT-DIAGNOSTIC", path, "diagnostic HTTP status is invalid"
        )
    remediation_refs = diagnostic.get("remediationRefs")
    if (
        not isinstance(remediation_refs, list)
        or len(remediation_refs) > 8
        or len(remediation_refs) != len(set(remediation_refs))
        or any(
            not isinstance(item, str)
            or len(item) > 200
            or REMEDIATION_REF_RE.fullmatch(item) is None
            for item in remediation_refs
        )
    ):
        raise ContractFailure(
            "LOGS-EVENT-DIAGNOSTIC", path, "diagnostic remediation references are invalid"
        )
    trace_id = diagnostic.get("traceId")
    span_id = diagnostic.get("spanId")
    if trace_id is not None and (
        not isinstance(trace_id, str) or TRACE_ID_RE.fullmatch(trace_id) is None
    ):
        raise ContractFailure(
            "LOGS-EVENT-DIAGNOSTIC", path, "diagnostic trace ID is invalid"
        )
    if span_id is not None and (
        not isinstance(span_id, str) or SPAN_ID_RE.fullmatch(span_id) is None
    ):
        raise ContractFailure(
            "LOGS-EVENT-DIAGNOSTIC", path, "diagnostic span ID is invalid"
        )


def validate_streams(
    root: Path,
    bundle: dict[str, Any],
    catalog: dict[str, dict[str, Any]],
) -> tuple[int, int]:
    directory = root / "logs"
    if not directory.is_dir():
        raise ContractFailure("LOGS-STORE-DIRECTORY", "logs", "log directory is missing")
    unsupported = sorted(
        item.name
        for item in directory.iterdir()
        if not item.is_file() or item.suffix != ".jsonl"
    )
    if unsupported:
        raise ContractFailure(
            "LOGS-STORE-PATH",
            "logs",
            "log directory contains an unsupported entry",
        )
    streams = sorted(directory.glob("*.jsonl"))
    if not streams:
        raise ContractFailure("LOGS-STORE-EMPTY", "logs", "no event stream exists")
    event_ids: set[str] = set()
    events_checked = 0
    for file_path in streams:
        stream = file_path.stem
        relative = file_path.relative_to(root).as_posix()
        if STREAM_RE.fullmatch(stream) is None:
            raise ContractFailure("LOGS-STORE-PATH", relative, "stream filename is invalid")
        try:
            lines = file_path.read_bytes().splitlines(keepends=True)
        except OSError as error:
            raise ContractFailure("LOGS-STORE-READ", relative, "stream is unreadable") from error
        if not lines:
            raise ContractFailure("LOGS-STORE-EMPTY", relative, "stream contains no events")
        previous_hash = ZERO_HASH
        prior_events: dict[str, dict[str, Any]] = {}
        for sequence, line in enumerate(lines, start=1):
            line_path = f"{relative}:{sequence}"
            if not line.endswith(b"\n") or line in {b"\n", b"\r\n"}:
                raise ContractFailure(
                    "LOGS-EVENT-CANONICAL",
                    line_path,
                    "event line is blank or lacks a final newline",
                )
            try:
                event = json.loads(line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as error:
                raise ContractFailure(
                    "LOGS-EVENT-JSON",
                    line_path,
                    "event line is not valid UTF-8 JSON",
                ) from error
            if canonical(event).encode("utf-8") + b"\n" != line:
                raise ContractFailure(
                    "LOGS-EVENT-CANONICAL",
                    line_path,
                    "event line is not canonical JSONL",
                )
            previous_hash = validate_event(
                event,
                bundle=bundle,
                catalog=catalog,
                root=root,
                path=line_path,
                stream=stream,
                sequence=sequence,
                previous_hash=previous_hash,
                prior_events=prior_events,
            )
            event_id = event["eventId"]
            if event_id in event_ids:
                raise ContractFailure("LOGS-EVENT-UNIQUE", line_path, "event ID is duplicated")
            event_ids.add(event_id)
            prior_events[event_id] = event
            events_checked += 1
    return len(streams), events_checked


def finding(error: ContractFailure) -> Finding:
    return Finding(
        code=DIAGNOSTIC_CODE,
        rule=error.rule,
        severity="ERROR",
        path=error.path,
        message=error.message,
    )


def validate_repository(root: Path) -> dict[str, Any]:
    findings: list[Finding] = []
    streams_checked = 0
    events_checked = 0
    errors_checked = 0
    contract_sha = ""
    try:
        bundle, contract_sha = load_contract(root)
    except ContractFailure as error:
        findings.append(finding(error))
        return report(findings, contract_sha, streams_checked, events_checked, errors_checked)
    for action in (
        lambda: validate_proto(root, bundle),
    ):
        try:
            action()
        except ContractFailure as error:
            findings.append(finding(error))
    catalog: dict[str, dict[str, Any]] = {}
    try:
        catalog = load_error_catalog(root, bundle)
        errors_checked = len(catalog)
    except ContractFailure as error:
        findings.append(finding(error))
    if catalog:
        try:
            streams_checked, events_checked = validate_streams(root, bundle, catalog)
        except ContractFailure as error:
            findings.append(finding(error))
    return report(findings, contract_sha, streams_checked, events_checked, errors_checked)


def report(
    findings: list[Finding],
    contract_sha: str,
    streams_checked: int,
    events_checked: int,
    errors_checked: int,
) -> dict[str, Any]:
    return {
        "schema": "wellmanifest.logs/validation-report/v1",
        "valid": not findings,
        "contractSha256": contract_sha,
        "streamsChecked": streams_checked,
        "eventsChecked": events_checked,
        "errorDefinitionsChecked": errors_checked,
        "findings": [asdict(item) for item in findings],
    }


def validate_request(bundle: dict[str, Any], value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContractFailure("LOGS-REQUEST-FIELDS", "request", "request must be an object")
    operation = value.get("operation")
    if operation == "inspect":
        request = exact_fields(
            value,
            {"schema", "operation", "processRef"},
            rule="LOGS-REQUEST-FIELDS",
            path="request",
        )
        expected_process = EXPECTED_PROCESSES["inspect"]
    elif operation == "plan_append":
        request = exact_fields(
            value,
            {
                "schema",
                "operation",
                "processRef",
                "stream",
                "expectedVersion",
                "eventRef",
                "eventSha256",
            },
            rule="LOGS-REQUEST-FIELDS",
            path="request",
        )
        expected_process = EXPECTED_PROCESSES["planAppend"]
        stream = request.get("stream")
        version = request.get("expectedVersion")
        event_ref = request.get("eventRef")
        event_sha = request.get("eventSha256")
        if not isinstance(stream, str) or STREAM_RE.fullmatch(stream) is None:
            raise ContractFailure("LOGS-REQUEST-STREAM", "request", "request stream is invalid")
        if isinstance(version, bool) or not isinstance(version, int) or not 0 <= version <= 9007199254740991:
            raise ContractFailure("LOGS-REQUEST-VERSION", "request", "expected version is invalid")
        if not isinstance(event_ref, str) or ARTIFACT_RE.fullmatch(event_ref) is None:
            raise ContractFailure("LOGS-REQUEST-ARTIFACT", "request", "event artifact reference is invalid")
        if not isinstance(event_sha, str) or SHA_RE.fullmatch(event_sha) is None:
            raise ContractFailure("LOGS-REQUEST-DIGEST", "request", "event artifact digest is invalid")
    else:
        raise ContractFailure(
            "LOGS-REQUEST-OPERATION",
            "request",
            "request operation is not inspect or propose-only plan_append",
        )
    if request.get("schema") != "wellmanifest.logs/request/v1":
        raise ContractFailure("LOGS-REQUEST-SCHEMA", "request", "request schema is unsupported")
    if request.get("processRef") != expected_process:
        raise ContractFailure("LOGS-REQUEST-PROCESS", "request", "request process does not match operation")
    if not isinstance(bundle.get("requestGbnf"), str):
        raise ContractFailure("LOGS-CONTRACT-GRAMMAR", "request", "request grammar is unavailable")
    return copy.deepcopy(request)


def copy_fixture(source: Path, destination: Path) -> None:
    for relative in (
        *LEGACY_CONTRACT_PATHS,
        CONTRACT_PATH,
        Path("proto/wellmanifest/logs/v1/logs.proto"),
        Path("proto/current/wellmanifest/logs/v1/logs.proto"),
        Path("proto/v0.5/wellmanifest/logs/v1/logs.proto"),
        Path(HELP_PATH),
        Path("logs/control.jsonl"),
        Path("logs/continuity.jsonl"),
    ):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)


def rewrite_event_at(path: Path, index: int, mutate: Any) -> None:
    events = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line]
    if index < 0:
        index += len(events)
    event = events[index]
    mutate(event)
    event["eventHash"] = calculate_event_hash(event)
    for successor_index in range(index + 1, len(events)):
        events[successor_index]["previousHash"] = events[successor_index - 1]["eventHash"]
        events[successor_index]["eventHash"] = calculate_event_hash(events[successor_index])
    path.write_text("".join(canonical(item) + "\n" for item in events), encoding="utf-8")


def rewrite_event(path: Path, mutate: Any) -> None:
    rewrite_event_at(path, -1, mutate)


def assert_valid(root: Path, label: str) -> None:
    result = validate_repository(root)
    if not result["valid"]:
        raise AssertionError(f"{label} was rejected: {result['findings']}")


def assert_invalid(root: Path, rule: str) -> None:
    result = validate_repository(root)
    rules = {item["rule"] for item in result["findings"]}
    if result["valid"] or rule not in rules:
        raise AssertionError(f"expected {rule}, observed {sorted(rules)}")


def write_adopter_error_fixture(
    root: Path,
    contract_sha: str,
    *,
    codes: tuple[str, ...] = ("ONEDEV-TEST-001",),
) -> Path:
    errors = root / "errors"
    errors.mkdir(parents=True)
    for code in codes:
        title = "Concurrent coordinator cycle was safely rejected"
        definition = {
            "category": "CONCURRENCY",
            "causes": ["Another coordinator still owns the process lease"],
            "code": code,
            "doNot": ["Do not delete a live lease file or replay the status write"],
            "meaning": "The requested cycle did not run because another process owns the serialized coordinator boundary.",
            "owner": "service:onedev-agent",
            "relatedEventTypes": ["error_raised", "remediation_completed"],
            "remediation": ["Let the owning cycle finish or verify that its process terminated"],
            "schema": "wellmanifest.logs/error/v1",
            "severity": "WARNING",
            "title": title,
            "verification": ["Run the coordinator concurrency regression test"],
            "version": 1,
        }
        (errors / f"{code}.md").write_text(
            f"# {code}: {title}\n\n"
            "## Error DSL\n\n"
            f"```log-error-dsl\n{canonical(definition)}\n```\n\n"
            "## Situation\n\nA second coordinator attempted an overlapping cycle.\n\n"
            "## Meaning\n\nThe active owner retains exclusive status and queue authority.\n\n"
            "## Safe resolution\n\nWait for the owner or verify process termination before retrying.\n\n"
            "## Verification\n\nRun the deterministic concurrency regression.\n\n"
            "## Do not\n\nDo not remove a lease held by a live process.\n\n"
            "## Related events\n\nUse error_raised and remediation_completed.\n",
            encoding="utf-8",
        )
    catalog = root / "logs-error-catalog.v1.json"
    catalog.write_text(
        json.dumps(
            {
                "schema": "wellmanifest.logs/adopter-error-catalog/v1",
                "namespace": "ONEDEV",
                "contractSha256": contract_sha,
                "errorsDirectory": "errors",
                "diagnosticCodes": sorted(codes),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return catalog


def assert_error_adoption_invalid(source: Path, catalog: Path, rule: str) -> None:
    result = validate_adopted_error_catalog(source, catalog)
    rules = {item["rule"] for item in result["findings"]}
    if result["valid"] or rule not in rules:
        raise AssertionError(f"expected adopter rule {rule}, observed {sorted(rules)}")


def run_self_test(source: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="wellmanifest-logs-") as temporary:
        baseline = Path(temporary) / "baseline"
        copy_fixture(source, baseline)
        valid = validate_repository(baseline)
        if not valid["valid"]:
            raise AssertionError(f"baseline failed: {valid['findings']}")
        fixture_types = [
            json.loads(line)["eventType"]
            for line in (baseline / "logs/continuity.jsonl").read_text("utf-8").splitlines()
        ]
        if set(fixture_types) != set(CONTINUITY_EVENT_TYPES) or len(fixture_types) != len(
            CONTINUITY_EVENT_TYPES
        ):
            raise AssertionError("continuity fixture does not cover each declared boundary once")

        extra = Path(temporary) / "extra"
        copy_fixture(source, extra)
        rewrite_event(extra / "logs/control.jsonl", lambda event: event.update({"payload": {}}))
        assert_invalid(extra, "LOGS-EVENT-FIELDS")

        unsafe = Path(temporary) / "unsafe"
        copy_fixture(source, unsafe)
        rewrite_event(
            unsafe / "logs/control.jsonl",
            lambda event: event.update({"secretMaterialIncluded": True}),
        )
        assert_invalid(unsafe, "LOGS-EVENT-SAFETY")

        chain = Path(temporary) / "chain"
        copy_fixture(source, chain)
        rewrite_event(
            chain / "logs/control.jsonl",
            lambda event: event.update({"previousHash": "1" * 64}),
        )
        assert_invalid(chain, "LOGS-EVENT-CHAIN")

        evidence = Path(temporary) / "evidence"
        copy_fixture(source, evidence)
        rewrite_event(
            evidence / "logs/control.jsonl",
            lambda event: event["evidence"][0].update({"sha256": "2" * 64}),
        )
        assert_invalid(evidence, "LOGS-EVENT-EVIDENCE")

        undocumented = Path(temporary) / "undocumented"
        copy_fixture(source, undocumented)
        rewrite_event(
            undocumented / "logs/control.jsonl",
            lambda event: event.update({"code": "LOGS-NOT-DOCUMENTED"}),
        )
        assert_invalid(undocumented, "LOGS-EVENT-CODE")

        timestamp = Path(temporary) / "timestamp"
        copy_fixture(source, timestamp)
        rewrite_event(
            timestamp / "logs/control.jsonl",
            lambda event: event.update({"occurredAt": "2026-08-12 18:20:00Z"}),
        )
        assert_invalid(timestamp, "LOGS-EVENT-TIME")

        # v0.2 rules derived from the c2004 deployment. The positive case is the
        # point of the revision: a real deployment emits namespaced domain types
        # that no closed enum could ever hold.
        domain = Path(temporary) / "domain"
        copy_fixture(source, domain)
        rewrite_event(
            domain / "logs/control.jsonl",
            lambda event: event.update({"eventType": "ticket.status_change"}),
        )
        assert_valid(domain, "namespaced deployment event type")

        squat = Path(temporary) / "squat"
        copy_fixture(source, squat)
        rewrite_event(
            squat / "logs/control.jsonl",
            lambda event: event.update({"eventType": "logs.forged"}),
        )
        assert_invalid(squat, "LOGS-EVENT-TYPE")

        mode = Path(temporary) / "mode"
        copy_fixture(source, mode)
        rewrite_event(mode / "logs/control.jsonl", lambda event: event.update({"mode": "apply"}))
        assert_invalid(mode, "LOGS-EVENT-MODE")

        origin = Path(temporary) / "origin"
        copy_fixture(source, origin)
        rewrite_event(
            origin / "logs/control.jsonl",
            lambda event: event.update({"source": "Logs.Bootstrap"}),
        )
        assert_invalid(origin, "LOGS-EVENT-SOURCE")

        unbound = Path(temporary) / "unbound"
        copy_fixture(source, unbound)
        rewrite_event(unbound / "logs/control.jsonl", lambda event: event.update({"inputHash": "-"}))
        assert_invalid(unbound, "LOGS-EVENT-INPUT")

        # The c2004 stream carried "-" on every receipt for 315 events, which
        # made an unexecuted event indistinguishable from an executed one.
        placeholder = Path(temporary) / "placeholder"
        copy_fixture(source, placeholder)
        rewrite_event(
            placeholder / "logs/control.jsonl",
            lambda event: event.update({"receiptRef": "-"}),
        )
        assert_invalid(placeholder, "LOGS-EVENT-RECEIPT")

        state = Path(temporary) / "state"
        copy_fixture(source, state)
        rewrite_event(
            state / "logs/control.jsonl",
            lambda event: event.update({"subjectState": "SUCCEEDED "}),
        )
        assert_invalid(state, "LOGS-EVENT-STATE")

        diagnostic = Path(temporary) / "diagnostic"
        copy_fixture(source, diagnostic)
        rewrite_event(
            diagnostic / "logs/control.jsonl",
            lambda event: event.update(
                {
                    "diagnostic": {
                        "phase": "requesting_link",
                        "status": "failed",
                        "retryable": True,
                        "attempt": 2,
                        "attempts": 3,
                        "durationMs": 1501,
                        "endpointRef": "http://127.0.0.1:18081",
                        "transportCode": "ECONNREFUSED",
                        "httpStatus": None,
                        "remediationRefs": ["error://subactor/login-endpoint-unreachable"],
                        "traceId": "1" * 32,
                        "spanId": "2" * 16,
                    }
                }
            ),
        )
        assert_valid(diagnostic, "typed operational diagnostic")

        credential_endpoint = Path(temporary) / "credential-endpoint"
        copy_fixture(source, credential_endpoint)
        rewrite_event(
            credential_endpoint / "logs/control.jsonl",
            lambda event: event.update(
                {
                    "diagnostic": {
                        "phase": "requesting_link",
                        "status": "failed",
                        "retryable": False,
                        "attempt": 1,
                        "attempts": 1,
                        "durationMs": 1,
                        "endpointRef": "https://user:placeholder@example.test/login?session=placeholder",
                        "transportCode": None,
                        "httpStatus": 401,
                        "remediationRefs": [],
                        "traceId": None,
                        "spanId": None,
                    }
                }
            ),
        )
        assert_invalid(credential_endpoint, "LOGS-EVENT-DIAGNOSTIC")

        attempt_order = Path(temporary) / "attempt-order"
        copy_fixture(source, attempt_order)
        rewrite_event(
            attempt_order / "logs/control.jsonl",
            lambda event: event.update(
                {
                    "diagnostic": {
                        "phase": "polling_approval",
                        "status": "retrying",
                        "retryable": True,
                        "attempt": 3,
                        "attempts": 2,
                        "durationMs": 10,
                        "endpointRef": "endpoint:founder-control",
                        "transportCode": None,
                        "httpStatus": None,
                        "remediationRefs": ["knowledge://subactor/login/v1"],
                        "traceId": None,
                        "spanId": None,
                    }
                }
            ),
        )
        assert_invalid(attempt_order, "LOGS-EVENT-DIAGNOSTIC")

        missing_continuity = Path(temporary) / "missing-continuity"
        copy_fixture(source, missing_continuity)
        rewrite_event_at(
            missing_continuity / "logs/continuity.jsonl",
            0,
            lambda event: event.pop("continuity"),
        )
        assert_invalid(missing_continuity, "LOGS-EVENT-CONTINUITY")

        for forbidden_field in (
            "rawPrompt",
            "rawDiff",
            "secret",
            "path",
            "hostPath",
            "toolStdout",
            "toolStderr",
        ):
            forbidden = Path(temporary) / f"forbidden-{forbidden_field.lower()}"
            copy_fixture(source, forbidden)
            rewrite_event_at(
                forbidden / "logs/continuity.jsonl",
                3,
                lambda event, field=forbidden_field: event["continuity"].update(
                    {field: "excluded"}
                ),
            )
            assert_invalid(forbidden, "LOGS-EVENT-CONTINUITY")

        host_path_receipt = Path(temporary) / "host-path-receipt"
        copy_fixture(source, host_path_receipt)
        rewrite_event_at(
            host_path_receipt / "logs/continuity.jsonl",
            3,
            lambda event: event["continuity"].update(
                {"executionReceiptRef": "receipt:///home/user/tool-output"}
            ),
        )
        assert_invalid(host_path_receipt, "LOGS-EVENT-CONTINUITY")

        wrong_cause = Path(temporary) / "wrong-continuity-cause"
        copy_fixture(source, wrong_cause)
        rewrite_event(
            wrong_cause / "logs/continuity.jsonl",
            lambda event: event.update({"causationId": "event:continuity:001"}),
        )
        assert_invalid(wrong_cause, "LOGS-EVENT-CONTINUITY-CAUSE")

        resume_digest = Path(temporary) / "resume-digest"
        copy_fixture(source, resume_digest)
        rewrite_event_at(
            resume_digest / "logs/continuity.jsonl",
            5,
            lambda event: event["continuity"].update({"snapshotDigest": "f" * 64}),
        )
        assert_invalid(resume_digest, "LOGS-EVENT-CONTINUITY-DIGEST")

        pair_digest = Path(temporary) / "pair-digest"
        copy_fixture(source, pair_digest)
        rewrite_event_at(
            pair_digest / "logs/continuity.jsonl",
            3,
            lambda event: event["continuity"].update({"requestDigest": "e" * 64}),
        )
        assert_invalid(pair_digest, "LOGS-EVENT-CONTINUITY-DIGEST")

        for label, event_index, digest_field in (
            ("commit-slice", 10, "sliceDigest"),
            ("push-commit", 11, "commitDigest"),
            ("push-completion-plan", 12, "pushPlanDigest"),
        ):
            publication_digest = Path(temporary) / label
            copy_fixture(source, publication_digest)
            rewrite_event_at(
                publication_digest / "logs/continuity.jsonl",
                event_index,
                lambda event, field=digest_field: event["continuity"].update(
                    {field: "d" * 64}
                ),
            )
            assert_invalid(publication_digest, "LOGS-EVENT-CONTINUITY-DIGEST")

        merged_publication = Path(temporary) / "merged-publication"
        copy_fixture(source, merged_publication)
        rewrite_event_at(
            merged_publication / "logs/continuity.jsonl",
            10,
            lambda event: event.update({"eventType": "git.push_started"}),
        )
        assert_invalid(merged_publication, "LOGS-EVENT-CONTINUITY")

        wrong_resume_decision = Path(temporary) / "wrong-resume-decision"
        copy_fixture(source, wrong_resume_decision)
        rewrite_event_at(
            wrong_resume_decision / "logs/continuity.jsonl",
            6,
            lambda event: event.update({"outcome": "ACCEPTED", "subjectState": "resume"}),
        )
        assert_invalid(
            wrong_resume_decision,
            "LOGS-EVENT-CONTINUITY-DECISION",
        )

        matching_resume = Path(temporary) / "matching-resume"
        copy_fixture(source, matching_resume)
        matching_events = [
            json.loads(line)
            for line in (matching_resume / "logs/continuity.jsonl")
            .read_text("utf-8")
            .splitlines()
        ]
        expected_state = matching_events[5]["continuity"]["expectedStateDigest"]
        rewrite_event_at(
            matching_resume / "logs/continuity.jsonl",
            5,
            lambda event: event["continuity"].update(
                {"observedStateDigest": expected_state}
            ),
        )
        rewrite_event_at(
            matching_resume / "logs/continuity.jsonl",
            6,
            lambda event: event.update({"outcome": "ACCEPTED", "subjectState": "resume"}),
        )
        assert_valid(matching_resume, "resume decision after a matching observation")

        generic_payload = Path(temporary) / "generic-payload"
        copy_fixture(source, generic_payload)
        rewrite_event(
            generic_payload / "logs/control.jsonl",
            lambda event: event.update(
                {"continuity": {"sessionDigest": "1" * 64}}
            ),
        )
        assert_invalid(generic_payload, "LOGS-EVENT-CONTINUITY")

        docs = Path(temporary) / "docs"
        copy_fixture(source, docs)
        page = docs / HELP_PATH
        page.write_text(page.read_text("utf-8").replace("## Do not\n", "## Unsafe shortcuts\n"), "utf-8")
        assert_invalid(docs, "LOGS-DOC-SECTIONS")

        title = Path(temporary) / "title"
        copy_fixture(source, title)
        page = title / HELP_PATH
        page.write_text(
            page.read_text("utf-8").replace("# LOGS-VALIDATION-001:", "# LOGS-WRONG:"),
            "utf-8",
        )
        assert_invalid(title, "LOGS-DOC-TITLE")

        grammar = Path(temporary) / "grammar"
        copy_fixture(source, grammar)
        contract = read_json(
            grammar / CONTRACT_PATH,
            rule="SELF-TEST",
            label="self-test contract",
        )
        contract["requestGbnf"] = contract["requestGbnf"].replace("plan_append", "append")
        (grammar / CONTRACT_PATH).write_text(json.dumps(contract, indent=2) + "\n", "utf-8")
        assert_invalid(grammar, "LOGS-CONTRACT-GRAMMAR")

        bundle, _ = load_contract(source)
        inspect = {
            "schema": "wellmanifest.logs/request/v1",
            "operation": "inspect",
            "processRef": EXPECTED_PROCESSES["inspect"],
        }
        validate_request(bundle, inspect)
        plan = {
            "schema": "wellmanifest.logs/request/v1",
            "operation": "plan_append",
            "processRef": EXPECTED_PROCESSES["planAppend"],
            "stream": "control",
            "expectedVersion": 1,
            "eventRef": "artifact://wellmanifest.dev/logs/event/r1",
            "eventSha256": "1" * 64,
        }
        validate_request(bundle, plan)
        for invalid in (
            {**inspect, "grant_ref": "grant:forged"},
            {**inspect, "operation": "append"},
        ):
            try:
                validate_request(bundle, invalid)
            except ContractFailure:
                pass
            else:
                raise AssertionError("authority-bearing request was accepted")

        canonical_schema = Path(temporary) / "canonical-event.schema.json"
        canonical_schema.write_text(
            json.dumps(bundle["schemas"]["event"], indent=2) + "\n",
            encoding="utf-8",
        )
        if not validate_adopted_event_schema(source, canonical_schema)["valid"]:
            raise AssertionError("canonical adopted schema was rejected")

        stale_schema = Path(temporary) / "stale-event.schema.json"
        stale = copy.deepcopy(bundle["schemas"]["event"])
        stale["required"].remove("inputHash")
        stale["properties"].pop("inputHash")
        stale_schema.write_text(json.dumps(stale, indent=2) + "\n", encoding="utf-8")
        stale_result = validate_adopted_event_schema(source, stale_schema)
        if (
            stale_result["valid"]
            or stale_result["findings"][0]["rule"]
            != "LOGS-ADOPTION-SCHEMA-DRIFT"
        ):
            raise AssertionError("stale adopted schema was accepted")

        adopter = Path(temporary) / "adopter"
        adopter_catalog = write_adopter_error_fixture(adopter, load_contract(source)[1])
        adopted = validate_adopted_error_catalog(source, adopter_catalog)
        if not adopted["valid"] or adopted["errorDefinitionsChecked"] != 1:
            raise AssertionError(f"valid adopter error catalog was rejected: {adopted['findings']}")

        drift = Path(temporary) / "adopter-drift"
        shutil.copytree(adopter, drift)
        drift_catalog = drift / adopter_catalog.name
        drift_payload = read_json(drift_catalog, rule="SELF-TEST", label="adopter catalog")
        drift_payload["contractSha256"] = "0" * 64
        drift_catalog.write_text(json.dumps(drift_payload, indent=2) + "\n", encoding="utf-8")
        assert_error_adoption_invalid(source, drift_catalog, "LOGS-ADOPTION-ERROR-CONTRACT-DRIFT")

        substituted = Path(temporary) / "adopter-substituted"
        shutil.copytree(adopter, substituted)
        substituted_catalog = substituted / adopter_catalog.name
        substituted_payload = read_json(
            substituted_catalog,
            rule="SELF-TEST",
            label="adopter catalog",
        )
        substituted_payload["namespace"] = "SUBLLM"
        substituted_catalog.write_text(
            json.dumps(substituted_payload, indent=2) + "\n",
            encoding="utf-8",
        )
        assert_error_adoption_invalid(
            source,
            substituted_catalog,
            "LOGS-ADOPTION-ERROR-NAMESPACE",
        )

        reserved = Path(temporary) / "adopter-reserved"
        shutil.copytree(adopter, reserved)
        reserved_catalog = reserved / adopter_catalog.name
        reserved_payload = read_json(reserved_catalog, rule="SELF-TEST", label="adopter catalog")
        reserved_payload["namespace"] = "LOGS"
        reserved_catalog.write_text(json.dumps(reserved_payload, indent=2) + "\n", encoding="utf-8")
        assert_error_adoption_invalid(
            source,
            reserved_catalog,
            "LOGS-ADOPTION-ERROR-NAMESPACE",
        )

        missing = Path(temporary) / "adopter-missing"
        shutil.copytree(adopter, missing)
        (missing / "errors/ONEDEV-TEST-001.md").unlink()
        assert_error_adoption_invalid(
            source,
            missing / adopter_catalog.name,
            "LOGS-DOC-CATALOG",
        )

        extra = Path(temporary) / "adopter-extra"
        extra_catalog = write_adopter_error_fixture(
            extra,
            load_contract(source)[1],
            codes=("ONEDEV-EXTRA-001", "ONEDEV-TEST-001"),
        )
        extra_payload = read_json(extra_catalog, rule="SELF-TEST", label="adopter catalog")
        extra_payload["diagnosticCodes"] = ["ONEDEV-TEST-001"]
        extra_catalog.write_text(json.dumps(extra_payload, indent=2) + "\n", encoding="utf-8")
        assert_error_adoption_invalid(source, extra_catalog, "LOGS-DOC-CATALOG")
    print("logs conformance self-test: PASS (continuity and adversarial checks)")


def print_report(result: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(result, indent=2, sort_keys=True))
        return
    if result["valid"]:
        print(
            "LOGS-PASS: "
            f"{result['streamsChecked']} stream(s), "
            f"{result['eventsChecked']} event(s), "
            f"{result['errorDefinitionsChecked']} error definition(s)"
        )
        return
    for item in result["findings"]:
        print(
            f"{item['code']} {item['severity']} [{item['rule']}] "
            f"{item['path']}: {item['message']} (help: {item['helpPath']})"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate repository projections")
    validate.add_argument("--root", type=Path, default=Path("."))
    validate.add_argument("--format", choices=("text", "json"), default="text")
    request = subparsers.add_parser("request", help="validate a propose-only request")
    request.add_argument("--root", type=Path, default=Path("."))
    request.add_argument("--request", type=Path, required=True)
    request.add_argument("--format", choices=("text", "json"), default="text")
    adoption = subparsers.add_parser(
        "adoption", help="validate a consumer's adopted event schema"
    )
    adoption.add_argument("--root", type=Path, default=Path("."))
    adoption.add_argument("--event-schema", type=Path, required=True)
    adoption.add_argument("--format", choices=("text", "json"), default="text")
    error_adoption = subparsers.add_parser(
        "error-adoption", help="validate a consumer-owned error catalog and runbooks"
    )
    error_adoption.add_argument("--root", type=Path, default=Path("."))
    error_adoption.add_argument("--catalog", type=Path, required=True)
    error_adoption.add_argument("--format", choices=("text", "json"), default="text")
    subparsers.add_parser("self-test", help="run positive and adversarial conformance")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    source_root = Path(__file__).resolve().parents[1]
    if args.command == "self-test":
        run_self_test(source_root)
        return 0
    root = args.root.resolve()
    if args.command == "validate":
        result = validate_repository(root)
        print_report(result, args.format)
        return 0 if result["valid"] else 1
    if args.command == "adoption":
        result = validate_adopted_event_schema(root, args.event_schema.resolve())
        if args.format == "json":
            print(json.dumps(result, indent=2, sort_keys=True))
        elif result["valid"]:
            print(
                "LOGS-ADOPTION-PASS: event schema matches canonical contract "
                f"{result['contractSha256']}"
            )
        else:
            for item in result["findings"]:
                print(
                    f"{item['code']} {item['severity']} [{item['rule']}] "
                    f"{item['path']}: {item['message']} "
                    f"(help: {item['helpPath']})"
                )
        return 0 if result["valid"] else 1
    if args.command == "error-adoption":
        result = validate_adopted_error_catalog(root, args.catalog.resolve())
        if args.format == "json":
            print(json.dumps(result, indent=2, sort_keys=True))
        elif result["valid"]:
            print(
                "LOGS-ERROR-ADOPTION-PASS: "
                f"{result['errorDefinitionsChecked']} error definition(s) match "
                f"canonical contract {result['contractSha256']}"
            )
        else:
            for item in result["findings"]:
                print(
                    f"{item['code']} {item['severity']} [{item['rule']}] "
                    f"{item['path']}: {item['message']} "
                    f"(help: {item['helpPath']})"
                )
        return 0 if result["valid"] else 1
    try:
        bundle, _ = load_contract(root)
        value = read_json(args.request, rule="LOGS-REQUEST-JSON", label="request")
        normalized = validate_request(bundle, value)
    except ContractFailure as error:
        result = report([finding(error)], "", 0, 0, 0)
        print_report(result, args.format)
        return 1
    if args.format == "json":
        print(json.dumps(normalized, indent=2, sort_keys=True))
    else:
        print(f"LOGS-REQUEST-PASS: {normalized['operation']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
