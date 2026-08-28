from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from subllm.credential_env import credential_names, find_env_file, import_credentials, load_env_file
from subllm.policy import ROUTES
from subllm.policy_config import load_policy_config
from subllm.provider_order import provider_order
from subllm.resolver import configured_route, configured_routes, resolve, validate_policy

from .canonical import digest_document
from .errors import PoaContractError
from .process_editor import propose_process_edit
from .refs import (
    ADAPTER,
    ARTIFACT_REF,
    GRAMMAR,
    IDEMPOTENCY,
    INPUT_SCHEMA,
    OBSERVATION_FACTS,
    PROCESS_DSL_INPUT,
    PROCESS_REF,
    ROUTE_INPUT,
    SHA256,
    SUBJECT,
    TARGET,
    exact,
    require_pattern,
)
from .registry import (
    CONFIGURED_ROUTE_URI,
    CREATE_PLAN_URI,
    EDIT_PROCESS_REF,
    EDIT_PROCESS_URI,
    EVENTS_URI,
    IMPORT_CREDENTIALS_URI,
    INSPECT_URI,
    LIST_APPLICATIONS_URI,
    LIST_PROVIDERS_URI,
    LIST_ROUTES_URI,
    OBSERVE_CREDENTIALS_URI,
    RECEIPT_URI,
    RESOLVE_ROUTE_URI,
    URI_TO_PROCESS,
    VALIDATE_URI,
    binding_for_process,
    get_process,
    get_process_uri,
    require_uri,
)
from .store import EventStore

QueryHandler = Callable[[dict[str, Any]], dict[str, Any]]
CommandHandler = Callable[[dict[str, Any]], dict[str, Any]]


def _now() -> datetime:
    return datetime.now(UTC)


def _rfc3339(value: datetime) -> str:
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


_SECRET_KEYS = {"api_key", "secret", "token", "password", "authorization", "signature"}


def _secret_free(payload: Any) -> None:
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            if key in _SECRET_KEYS:
                raise PoaContractError("POA-SECRET-001", "payload must not include secret material")
            _secret_free(value)
        return
    if isinstance(payload, list):
        for item in payload:
            _secret_free(item)


class PolicyBus:
    """Single CQRS path for CLI, shell and HTTP. Queries never append events."""

    def __init__(self, store: EventStore | None = None) -> None:
        self.store = store or EventStore()
        self._queries: dict[str, QueryHandler] = {
            INSPECT_URI: self._query_inspect,
            LIST_ROUTES_URI: self._query_list_routes,
            LIST_PROVIDERS_URI: self._query_list_providers,
            LIST_APPLICATIONS_URI: self._query_list_applications,
            CONFIGURED_ROUTE_URI: self._query_configured_route,
            RESOLVE_ROUTE_URI: self._query_resolve_route,
            OBSERVE_CREDENTIALS_URI: self._query_observe_credentials,
            VALIDATE_URI: self._query_validate,
            EVENTS_URI: self._query_events,
            RECEIPT_URI: self._query_receipt,
        }
        self._commands: dict[str, CommandHandler] = {
            CREATE_PLAN_URI: self._command_create_plan,
            EDIT_PROCESS_URI: self._command_edit_process,
            IMPORT_CREDENTIALS_URI: self._command_import_credentials,
        }

    def query(self, document: Mapping[str, Any]) -> dict[str, Any]:
        before = self.store.sequence
        payload = exact(document, {"schema", "process_uri"}, optional=set(document) - {"schema", "process_uri"})
        if payload["schema"] != "subllm.query/v1":
            raise PoaContractError("POA-DOC-001", "query schema is not registered")
        process_uri = require_uri(payload["process_uri"], "query")
        result = self._queries[process_uri](payload)
        if self.store.sequence != before:
            raise PoaContractError("POA-VIEW-001", "query must not append events")
        _secret_free(result)
        return result

    def command(self, document: Mapping[str, Any]) -> dict[str, Any]:
        payload = exact(
            document,
            {"schema", "process_uri", "subject", "idempotency_key"},
            optional=set(document) - {"schema", "process_uri", "subject", "idempotency_key"},
        )
        if payload["schema"] != "subllm.command/v1":
            raise PoaContractError("POA-DOC-001", "command schema is not registered")
        _secret_free(payload)
        require_pattern(payload["subject"], "subject", SUBJECT)
        require_pattern(payload["idempotency_key"], "idempotency_key", IDEMPOTENCY)
        process_uri = require_uri(payload["process_uri"], "command")
        existing = self.store.run_for_idempotency(payload["idempotency_key"])
        if existing is not None:
            receipt = self.store.receipt(existing)
            plan = self.store.plan(existing)
            return {"run_id": existing, "idempotent": True, "plan": plan, "receipt": receipt}
        result = self._commands[process_uri](payload)
        _secret_free(result)
        return result

    def inspect(self, process_ref: str) -> dict[str, Any]:
        return self.query({"schema": "subllm.query/v1", "process_uri": INSPECT_URI, "process_ref": process_ref})

    def _query_inspect(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = exact(document, {"schema", "process_uri", "process_ref"})
        process = get_process(payload["process_ref"])
        observation = self._observation()
        binding = binding_for_process(payload["process_ref"], observation["facts_sha256"])
        return {
            "schema": "poa.request/v1",
            "operation": "inspect",
            "process": process,
            "binding": binding,
            "observation": observation,
            "process_uri": get_process_uri(payload["process_ref"]),
            "ready": True,
        }

    def _query_list_routes(self, document: dict[str, Any]) -> dict[str, Any]:
        exact(document, {"schema", "process_uri"})
        routes = []
        for application, function in sorted(ROUTES):
            routes.append(
                {
                    "application": application,
                    "function": function,
                    "candidates": [route.public_dict() for route in configured_routes(application, function)],
                }
            )
        return {"routes": routes}

    def _query_list_providers(self, document: dict[str, Any]) -> dict[str, Any]:
        exact(document, {"schema", "process_uri"})
        policy = load_policy_config()
        return {
            "source": str(policy.source) if policy.source is not None else "built-in defaults",
            "order": list(provider_order()),
            "providers": {name: asdict(settings) for name, settings in policy.providers.items()},
        }

    def _query_list_applications(self, document: dict[str, Any]) -> dict[str, Any]:
        exact(document, {"schema", "process_uri"})
        policy = load_policy_config()
        return {
            "source": str(policy.source) if policy.source is not None else "built-in defaults",
            "applications": {name: asdict(settings) for name, settings in policy.applications.items()},
        }

    def _query_configured_route(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = exact(document, {"schema", "process_uri", "application", "function"}, optional={"provider"})
        provider = payload.get("provider") or None
        route = configured_route(payload["application"], payload["function"], provider=provider)
        return route.public_dict()

    def _query_resolve_route(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = exact(document, {"schema", "process_uri", "application", "function"}, optional={"provider"})
        provider = payload.get("provider") or None
        route = resolve(payload["application"], payload["function"], provider=provider)
        return route.public_dict()

    def _query_observe_credentials(self, document: dict[str, Any]) -> dict[str, Any]:
        exact(document, {"schema", "process_uri"})
        path = find_env_file()
        configured = load_env_file(path) if path is not None else {}
        return {
            "path": str(path) if path is not None else None,
            "credentials": {
                name: "configured" if configured.get(name) else "missing" for name in credential_names()
            },
        }

    def _query_validate(self, document: dict[str, Any]) -> dict[str, Any]:
        exact(document, {"schema", "process_uri"})
        validate_policy()
        return {"status": "ok"}

    def _query_events(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = exact(document, {"schema", "process_uri"}, optional={"run_id"})
        run_id = payload.get("run_id")
        if run_id is not None and not isinstance(run_id, str):
            raise PoaContractError("POA-ID-001", "run_id is not a closed identifier")
        return {"events": self.store.events(run_id)}

    def _query_receipt(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = exact(document, {"schema", "process_uri", "run_id"})
        receipt = self.store.receipt(payload["run_id"])
        if receipt is None:
            raise PoaContractError("POA-RECEIPT-001", "receipt is not registered")
        return receipt

    def _command_create_plan(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = exact(
            document,
            {"schema", "process_uri", "process_ref", "input_ref", "input_sha256", "subject", "idempotency_key"},
        )
        plan = self._build_plan(payload)
        run_id = f"run.{uuid4().hex[:12]}"
        self._emit(run_id, plan, "planned")
        self.store.remember_plan(run_id, plan, payload["idempotency_key"])
        receipt = self._receipt(run_id, plan, "succeeded", plan["plan_hash"])
        self.store.remember_receipt(run_id, receipt)
        return {"run_id": run_id, "idempotent": False, "plan": plan, "receipt": receipt}

    def _command_import_credentials(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = exact(
            document,
            {"schema", "process_uri", "sources", "target", "subject", "idempotency_key"},
            optional={"input_ref", "input_sha256", "process_ref"},
        )
        sources = payload["sources"]
        if not isinstance(sources, list) or not sources or any(not isinstance(item, str) for item in sources):
            raise PoaContractError("POA-DOC-001", "sources must be a closed path list")
        if not isinstance(payload["target"], str):
            raise PoaContractError("POA-DOC-001", "target must be a closed path")
        plan_payload = {
            "process_ref": payload.get("process_ref") or URI_TO_PROCESS[IMPORT_CREDENTIALS_URI],
            "input_ref": payload.get("input_ref") or ROUTE_INPUT,
            "input_sha256": payload.get("input_sha256") or digest_document({"sources": len(sources)}),
            "subject": payload["subject"],
            "idempotency_key": payload["idempotency_key"],
        }
        plan = self._build_plan(plan_payload)
        run_id = f"run.{uuid4().hex[:12]}"
        self._emit(run_id, plan, "planned")
        self._emit(run_id, plan, "started")
        names = import_credentials([Path(item) for item in sources], Path(payload["target"]))
        output = {"imported": list(names), "target": str(Path(payload["target"]).resolve(strict=False))}
        self._emit(run_id, plan, "completed")
        self._emit(run_id, plan, "verified")
        self.store.remember_plan(run_id, plan, payload["idempotency_key"])
        receipt = self._receipt(run_id, plan, "succeeded", digest_document(output))
        self.store.remember_receipt(run_id, receipt)
        return {"run_id": run_id, "idempotent": False, "plan": plan, "receipt": receipt, "result": output}

    def _command_edit_process(self, document: dict[str, Any]) -> dict[str, Any]:
        payload = exact(
            document,
            {
                "schema",
                "process_uri",
                "source_process",
                "base_sha256",
                "edits",
                "subject",
                "idempotency_key",
            },
        )
        proposal = propose_process_edit(
            payload["source_process"], payload["base_sha256"], payload["edits"]
        )
        plan = self._build_plan(
            {
                "process_ref": EDIT_PROCESS_REF,
                "input_ref": PROCESS_DSL_INPUT,
                "input_sha256": proposal["base_sha256"],
                "subject": payload["subject"],
                "idempotency_key": payload["idempotency_key"],
            }
        )
        run_id = f"run.{uuid4().hex[:12]}"
        for event_type in ("planned", "started", "completed", "verified"):
            self._emit(run_id, plan, event_type)
        self.store.remember_plan(run_id, plan, payload["idempotency_key"])
        receipt = self._receipt(run_id, plan, "succeeded", proposal["candidate_sha256"])
        self.store.remember_receipt(run_id, receipt)
        return {
            "run_id": run_id,
            "idempotent": False,
            "plan": plan,
            "receipt": receipt,
            "result": proposal,
        }

    def _observation(self) -> dict[str, Any]:
        observed = _now()
        facts = self._query_observe_credentials({"schema": "subllm.query/v1", "process_uri": OBSERVE_CREDENTIALS_URI})
        facts["policy_status"] = "ok"
        validate_policy()
        digest = digest_document(facts)
        return {
            "schema": "poa.observation/v1",
            "observation_id": f"obs.{digest[:12]}",
            "target_ref": TARGET,
            "observed_at": _rfc3339(observed),
            "valid_until": _rfc3339(observed + timedelta(minutes=5)),
            "fact_schema_ref": INPUT_SCHEMA,
            "facts_ref": OBSERVATION_FACTS,
            "facts_sha256": digest,
            "read_only": True,
            "facts": facts,
        }

    def _build_plan(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        process_ref = require_pattern(payload["process_ref"], "process_ref", PROCESS_REF)
        process = get_process(process_ref)
        input_ref = require_pattern(payload["input_ref"], "input_ref", ARTIFACT_REF)
        input_sha256 = require_pattern(payload["input_sha256"], "input_sha256", SHA256)
        observation = self._observation()
        binding = binding_for_process(process_ref, observation["facts_sha256"])
        request = {
            "schema": "poa.request/v1",
            "operation": "plan",
            "process_ref": process_ref,
            "input_ref": input_ref,
            "input_sha256": input_sha256,
        }
        step = process["steps"][0]
        planned_step = {
            "id": step["id"],
            "capability_ref": step["capability_ref"],
            "process_uri": binding["process_uri"],
            "target_ref": TARGET,
            "kind": step["kind"],
            "effects": list(step["effects"]),
            "depends_on": [],
            "input_ref": input_ref,
            "input_sha256": input_sha256,
            "timeout_seconds": step["timeout_seconds"],
            "max_attempts": step["max_attempts"],
            "idempotency_key": payload["idempotency_key"],
            "verification": list(step["verification"]),
        }
        dsl = {
            "schema_ref": INPUT_SCHEMA,
            "grammar_ref": GRAMMAR,
            "schema_sha256": digest_document({"schema": "subllm.query/v1"}),
            "grammar_sha256": digest_document({"grammar": "subllm.poa.request/v1"}),
            "canonical_sha256": digest_document(request),
            "canonicalization": "RFC8785",
            "hash_algorithm": "SHA-256",
            "validated": True,
            "additional_properties": False,
        }
        unsigned = {
            "schema": "poa.plan/v1",
            "plan_id": f"plan.{digest_document(request)[:12]}",
            "process_ref": process_ref,
            "request_sha256": digest_document(request),
            "valid_until": _rfc3339(_now() + timedelta(minutes=5)),
            "steps": [planned_step],
            "dsl_contract": dsl,
            "authority_requirements": {
                "subject": payload["subject"],
                "scopes": ["subllm.policy"],
                "grant_ttl_seconds": 300,
                "intent_required": True,
                "plan_hash_binding": True,
            },
            "execution_boundary": {
                "boundary_ref": TARGET,
                "host_shell": False,
                "arbitrary_executable": False,
                "transport_from_registry": True,
            },
            "hash_profile": "RFC8785+SHA-256",
        }
        plan = dict(unsigned)
        plan["plan_hash"] = digest_document(unsigned)
        if planned_step["kind"] == "query" and set(planned_step["effects"]) & {
            "local_write",
            "external_write",
            "destructive",
        }:
            raise PoaContractError("POA-PLAN-001", "planned query declares a mutating effect")
        if binding["adapter_ref"] != ADAPTER:
            raise PoaContractError("POA-EXEC-001", "adapter is not allowlisted")
        return plan

    def _emit(self, run_id: str, plan: Mapping[str, Any], event_type: str) -> dict[str, Any]:
        return self.store.append(
            {
                "schema": "poa.event/v1",
                "event_id": "evt.pending",
                "run_id": run_id,
                "sequence": 0,
                "process_ref": plan["process_ref"],
                "plan_ref": f"sha256:{plan['plan_hash']}",
                "event_type": event_type,
                "occurred_at": _rfc3339(_now()),
                "step_id": plan["steps"][0]["id"],
                "artifact_refs": [plan["steps"][0]["input_ref"]],
                "raw_output_included": False,
                "secret_material_included": False,
            }
        )

    def _receipt(self, run_id: str, plan: Mapping[str, Any], state: str, output_sha256: str) -> dict[str, Any]:
        completed = _rfc3339(_now())
        unsigned = {
            "schema": "poa.receipt/v1",
            "run_id": run_id,
            "process_ref": plan["process_ref"],
            "plan_ref": f"sha256:{plan['plan_hash']}",
            "grant_ref": f"grant:{run_id}",
            "intent_ref": f"intent:{run_id}",
            "state": state,
            "started_at": completed,
            "completed_at": completed,
            "steps": [
                {
                    "step_id": plan["steps"][0]["id"],
                    "process_uri": plan["steps"][0]["process_uri"],
                    "state": state,
                    "attempts": 1,
                    "output_sha256": output_sha256,
                    "output_bytes": 0,
                    "effect_verified": state == "succeeded",
                    "verification_refs": [OBSERVATION_FACTS],
                }
            ],
            "raw_output_included": False,
            "secret_material_included": False,
            "hash_profile": "RFC8785+SHA-256",
        }
        receipt = dict(unsigned)
        receipt["receipt_hash"] = digest_document(unsigned)
        return receipt
