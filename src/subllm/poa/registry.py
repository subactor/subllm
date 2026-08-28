from __future__ import annotations

from copy import deepcopy
from typing import Any

from .errors import PoaContractError
from .refs import (
    ADAPTER,
    INPUT_SCHEMA,
    OUTPUT_SCHEMA,
    POLICY,
    PROCESS_REF,
    PROCESS_URI,
    TARGET,
    VERIFY_CAPABILITY,
    VERIFY_SCHEMA,
    require_pattern,
)

OWNER = "service:subllm"
PROCESS_OWNER_HOME = "subactor"
PROCESS_SHAPE = "runtime_service"

INSPECT_URI = "subllm://local/policy/query/inspect"
LIST_ROUTES_URI = "subllm://local/policy/query/list-routes"
LIST_PROVIDERS_URI = "subllm://local/policy/query/list-providers"
LIST_APPLICATIONS_URI = "subllm://local/policy/query/list-applications"
CONFIGURED_ROUTE_URI = "subllm://local/policy/query/configured-route"
RESOLVE_ROUTE_URI = "subllm://local/policy/query/resolve-route"
OBSERVE_CREDENTIALS_URI = "subllm://local/policy/query/observe-credentials"
VALIDATE_URI = "subllm://local/policy/query/validate"
EVENTS_URI = "subllm://local/policy/query/events"
RECEIPT_URI = "subllm://local/policy/query/receipt"
CREATE_PLAN_URI = "subllm://local/policy/command/create-plan"
IMPORT_CREDENTIALS_URI = "subllm://local/policy/command/import-credentials"
EDIT_PROCESS_URI = "subllm://local/policy/command/edit-process"

INSPECT_REF = "poa://subactor.subllm/process/inspect-policy/v1"
LIST_ROUTES_REF = "poa://subactor.subllm/process/list-routes/v1"
LIST_PROVIDERS_REF = "poa://subactor.subllm/process/list-providers/v1"
LIST_APPLICATIONS_REF = "poa://subactor.subllm/process/list-applications/v1"
CONFIGURED_ROUTE_REF = "poa://subactor.subllm/process/configured-route/v1"
RESOLVE_ROUTE_REF = "poa://subactor.subllm/process/resolve-route/v1"
OBSERVE_CREDENTIALS_REF = "poa://subactor.subllm/process/observe-credentials/v1"
VALIDATE_REF = "poa://subactor.subllm/process/validate-policy/v1"
EVENTS_REF = "poa://subactor.subllm/process/list-events/v1"
RECEIPT_REF = "poa://subactor.subllm/process/get-receipt/v1"
CREATE_PLAN_REF = "poa://subactor.subllm/process/create-plan/v1"
IMPORT_CREDENTIALS_REF = "poa://subactor.subllm/process/import-credentials/v1"
EDIT_PROCESS_REF = "poa://subactor.subllm/process/edit-process/v1"

CAP_INSPECT = "capability://subactor.subllm/policy/inspect/v1"
CAP_LIST = "capability://subactor.subllm/policy/list/v1"
CAP_RESOLVE = "capability://subactor.subllm/policy/resolve/v1"
CAP_OBSERVE = "capability://subactor.subllm/policy/observe/v1"
CAP_VALIDATE = "capability://subactor.subllm/policy/validate/v1"
CAP_JOURNAL = "capability://subactor.subllm/policy/journal/v1"
CAP_PLAN = "capability://subactor.subllm/policy/plan/v1"
CAP_IMPORT = "capability://subactor.subllm/policy/import-credentials/v1"
CAP_EDIT_PROCESS = "capability://subactor.subllm/policy/edit-process/v1"


def _verification() -> list[dict[str, str]]:
    return [{"capability_ref": VERIFY_CAPABILITY, "expectation_schema_ref": VERIFY_SCHEMA}]


def _step(
    step_id: str,
    capability_ref: str,
    kind: str,
    effects: list[str],
    *,
    requires_approval: bool = False,
    idempotency: str = "read_only",
) -> dict[str, Any]:
    return {
        "id": step_id,
        "capability_ref": capability_ref,
        "kind": kind,
        "effects": effects,
        "depends_on": [],
        "requires_approval": requires_approval,
        "timeout_seconds": 15,
        "max_attempts": 1,
        "idempotency": idempotency,
        "verification": _verification(),
    }


def _process(process_ref: str, title: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "poa.process/v1",
        "process_ref": process_ref,
        "title": title,
        "owner": OWNER,
        "input_schema_ref": INPUT_SCHEMA,
        "output_schema_ref": OUTPUT_SCHEMA,
        "policy_refs": [POLICY],
        "steps": steps,
    }


PROCESSES: dict[str, dict[str, Any]] = {
    INSPECT_REF: _process(
        INSPECT_REF,
        "Inspect a declared SubLLM process",
        [_step("inspect", CAP_INSPECT, "query", ["read_data"])],
    ),
    LIST_ROUTES_REF: _process(
        LIST_ROUTES_REF,
        "List configured application and function routes",
        [_step("list-routes", CAP_LIST, "query", ["read_data"])],
    ),
    LIST_PROVIDERS_REF: _process(
        LIST_PROVIDERS_REF,
        "List public provider enablement and defaults",
        [_step("list-providers", CAP_LIST, "query", ["read_data"])],
    ),
    LIST_APPLICATIONS_REF: _process(
        LIST_APPLICATIONS_REF,
        "List public application identity",
        [_step("list-applications", CAP_LIST, "query", ["read_data"])],
    ),
    CONFIGURED_ROUTE_REF: _process(
        CONFIGURED_ROUTE_REF,
        "Inspect one route without requiring a credential",
        [_step("configured-route", CAP_RESOLVE, "query", ["read_data"])],
    ),
    RESOLVE_ROUTE_REF: _process(
        RESOLVE_ROUTE_REF,
        "Resolve one route using credential presence, not the key value",
        [
            _step(
                "resolve-route",
                CAP_RESOLVE,
                "query",
                ["read_data", "credential_use"],
                requires_approval=True,
            )
        ],
    ),
    OBSERVE_CREDENTIALS_REF: _process(
        OBSERVE_CREDENTIALS_REF,
        "Observe credential names as configured or missing",
        [_step("observe-credentials", CAP_OBSERVE, "query", ["read_data"])],
    ),
    VALIDATE_REF: _process(
        VALIDATE_REF,
        "Validate the effective SubLLM policy",
        [_step("validate", CAP_VALIDATE, "query", ["read_data"])],
    ),
    EVENTS_REF: _process(
        EVENTS_REF,
        "Read the event journal projection",
        [_step("list-events", CAP_JOURNAL, "query", ["read_data"])],
    ),
    RECEIPT_REF: _process(
        RECEIPT_REF,
        "Read one terminal receipt",
        [_step("get-receipt", CAP_JOURNAL, "query", ["read_data"])],
    ),
    CREATE_PLAN_REF: _process(
        CREATE_PLAN_REF,
        "Create a secret-free dry plan for a declared process",
        [_step("create-plan", CAP_PLAN, "command", ["read_data"], idempotency="required")],
    ),
    IMPORT_CREDENTIALS_REF: _process(
        IMPORT_CREDENTIALS_REF,
        "Import provider credential names into the local ignored env file",
        [
            _step(
                "import-credentials",
                CAP_IMPORT,
                "command",
                ["local_write"],
                idempotency="required",
            )
        ],
    ),
    EDIT_PROCESS_REF: _process(
        EDIT_PROCESS_REF,
        "Validate a digest-bound LLM process DSL edit proposal",
        [
            _step(
                "edit-process",
                CAP_EDIT_PROCESS,
                "command",
                ["read_data"],
                idempotency="required",
            )
        ],
    ),
}

BINDINGS: dict[str, dict[str, Any]] = {
    CAP_INSPECT: {
        "schema": "poa.binding/v1",
        "binding_id": "bind.inspect",
        "capability_ref": CAP_INSPECT,
        "process_uri": INSPECT_URI,
        "target_ref": TARGET,
        "adapter_ref": ADAPTER,
        "priority": 0,
    },
    CAP_LIST: {
        "schema": "poa.binding/v1",
        "binding_id": "bind.list",
        "capability_ref": CAP_LIST,
        "process_uri": LIST_ROUTES_URI,
        "target_ref": TARGET,
        "adapter_ref": ADAPTER,
        "priority": 0,
    },
    CAP_RESOLVE: {
        "schema": "poa.binding/v1",
        "binding_id": "bind.resolve",
        "capability_ref": CAP_RESOLVE,
        "process_uri": CONFIGURED_ROUTE_URI,
        "target_ref": TARGET,
        "adapter_ref": ADAPTER,
        "priority": 0,
    },
    CAP_OBSERVE: {
        "schema": "poa.binding/v1",
        "binding_id": "bind.observe",
        "capability_ref": CAP_OBSERVE,
        "process_uri": OBSERVE_CREDENTIALS_URI,
        "target_ref": TARGET,
        "adapter_ref": ADAPTER,
        "priority": 0,
    },
    CAP_VALIDATE: {
        "schema": "poa.binding/v1",
        "binding_id": "bind.validate",
        "capability_ref": CAP_VALIDATE,
        "process_uri": VALIDATE_URI,
        "target_ref": TARGET,
        "adapter_ref": ADAPTER,
        "priority": 0,
    },
    CAP_JOURNAL: {
        "schema": "poa.binding/v1",
        "binding_id": "bind.journal",
        "capability_ref": CAP_JOURNAL,
        "process_uri": EVENTS_URI,
        "target_ref": TARGET,
        "adapter_ref": ADAPTER,
        "priority": 0,
    },
    CAP_PLAN: {
        "schema": "poa.binding/v1",
        "binding_id": "bind.plan",
        "capability_ref": CAP_PLAN,
        "process_uri": CREATE_PLAN_URI,
        "target_ref": TARGET,
        "adapter_ref": ADAPTER,
        "priority": 0,
    },
    CAP_IMPORT: {
        "schema": "poa.binding/v1",
        "binding_id": "bind.import",
        "capability_ref": CAP_IMPORT,
        "process_uri": IMPORT_CREDENTIALS_URI,
        "target_ref": TARGET,
        "adapter_ref": ADAPTER,
        "priority": 0,
    },
    CAP_EDIT_PROCESS: {
        "schema": "poa.binding/v1",
        "binding_id": "bind.edit-process",
        "capability_ref": CAP_EDIT_PROCESS,
        "process_uri": EDIT_PROCESS_URI,
        "target_ref": TARGET,
        "adapter_ref": ADAPTER,
        "priority": 0,
    },
}

PROCESS_URIS: dict[str, str] = {
    INSPECT_REF: INSPECT_URI,
    LIST_ROUTES_REF: LIST_ROUTES_URI,
    LIST_PROVIDERS_REF: LIST_PROVIDERS_URI,
    LIST_APPLICATIONS_REF: LIST_APPLICATIONS_URI,
    CONFIGURED_ROUTE_REF: CONFIGURED_ROUTE_URI,
    RESOLVE_ROUTE_REF: RESOLVE_ROUTE_URI,
    OBSERVE_CREDENTIALS_REF: OBSERVE_CREDENTIALS_URI,
    VALIDATE_REF: VALIDATE_URI,
    EVENTS_REF: EVENTS_URI,
    RECEIPT_REF: RECEIPT_URI,
    CREATE_PLAN_REF: CREATE_PLAN_URI,
    IMPORT_CREDENTIALS_REF: IMPORT_CREDENTIALS_URI,
    EDIT_PROCESS_REF: EDIT_PROCESS_URI,
}

URI_KIND = {
    INSPECT_URI: "query",
    LIST_ROUTES_URI: "query",
    LIST_PROVIDERS_URI: "query",
    LIST_APPLICATIONS_URI: "query",
    CONFIGURED_ROUTE_URI: "query",
    RESOLVE_ROUTE_URI: "query",
    OBSERVE_CREDENTIALS_URI: "query",
    VALIDATE_URI: "query",
    EVENTS_URI: "query",
    RECEIPT_URI: "query",
    CREATE_PLAN_URI: "command",
    IMPORT_CREDENTIALS_URI: "command",
    EDIT_PROCESS_URI: "command",
}

URI_TO_PROCESS = {uri: process_ref for process_ref, uri in PROCESS_URIS.items()}


def get_process(process_ref: str) -> dict[str, Any]:
    require_pattern(process_ref, "process_ref", PROCESS_REF)
    try:
        return deepcopy(PROCESSES[process_ref])
    except KeyError as exc:
        raise PoaContractError("POA-REGISTRY-001", "process is not registered") from exc


def get_process_uri(process_ref: str) -> str:
    get_process(process_ref)
    return PROCESS_URIS[process_ref]


def require_uri(process_uri: str, kind: str) -> str:
    require_pattern(process_uri, "process_uri", PROCESS_URI)
    expected = URI_KIND.get(process_uri)
    if expected is None:
        raise PoaContractError("POA-REGISTRY-001", "process URI is not registered")
    if expected != kind or f"/{kind}/" not in process_uri:
        raise PoaContractError("POA-REGISTRY-001", "process URI kind does not match the request")
    return process_uri


def binding_for_process(process_ref: str, observation_sha256: str) -> dict[str, Any]:
    process = get_process(process_ref)
    capability_ref = process["steps"][0]["capability_ref"]
    binding = deepcopy(BINDINGS[capability_ref])
    binding["process_uri"] = PROCESS_URIS[process_ref]
    binding["observation_ref"] = "artifact://subactor.subllm/observations/policy-facts/r1"
    binding["observation_sha256"] = observation_sha256
    return binding


def catalog_document() -> dict[str, Any]:
    return {
        "schema": "subllm.poa.catalog/v1",
        "home": PROCESS_OWNER_HOME,
        "shape": PROCESS_SHAPE,
        "adopt": [
            "wellmanifest/poa",
            "wellmanifest/env-dsl",
            "wellmanifest/modularity",
            "wellmanifest/new-project",
            "wellmanifest/policy-dsl",
        ],
        "single_exporter": "subactor/subllm",
        "processes": [get_process(process_ref) for process_ref in PROCESS_URIS],
        "uris": dict(PROCESS_URIS),
    }
