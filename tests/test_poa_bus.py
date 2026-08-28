from __future__ import annotations

import json
from pathlib import Path

import pytest

from subllm.poa import EventStore, PolicyBus, catalog_document
from subllm.poa.canonical import digest_document
from subllm.poa.errors import PoaContractError
from subllm.poa.refs import ROUTE_INPUT
from subllm.poa.registry import (
    CREATE_PLAN_URI,
    EDIT_PROCESS_REF,
    EDIT_PROCESS_URI,
    LIST_ROUTES_REF,
    LIST_ROUTES_URI,
    VALIDATE_REF,
    VALIDATE_URI,
)

ROOT = Path(__file__).resolve().parents[1]


def _editable_process() -> dict:
    return {
        "schema_version": "1.1",
        "process_id": "repair.v1",
        "entrypoint": "repair-agent",
        "required_inputs": ["doctor_issue"],
        "checklist": ["Reproduce", "Repair", "Validate"],
        "completion_criteria": ["validated"],
        "allowed_actions": ["apply_validated_patch"],
        "timeout_seconds": 900,
        "retry_policy": {
            "max_attempts": 3,
            "reuse_branch": True,
            "reuse_pull_request": True,
        },
        "required_artifacts": ["pull_request"],
        "decision_policy": {
            "mode": "controlled-hybrid",
            "strategy_order": [
                "deterministic-preconditions",
                "bounded-heuristics",
                "llm-editor-proposal",
                "deterministic-validation",
                "independent-publication",
            ],
            "deterministic_controls": [
                "schema",
                "scope",
                "authority",
                "base-digest",
                "idempotency",
            ],
            "heuristic": {"authority": "advisory", "fallback": "fail-closed"},
            "llm_editor": {
                "authority": "proposal-only",
                "editable_paths": [
                    "/checklist",
                    "/timeout_seconds",
                    "/retry_policy/max_attempts",
                ],
            },
            "publication": {
                "schema_validation": True,
                "exact_base_digest": True,
                "independent_validation": True,
            },
        },
    }


def test_query_does_not_append_events() -> None:
    bus = PolicyBus()
    result = bus.query({"schema": "subllm.query/v1", "process_uri": VALIDATE_URI})
    assert result == {"status": "ok"}
    assert bus.store.events() == []


def test_query_rejects_extra_fields() -> None:
    bus = PolicyBus()
    with pytest.raises(PoaContractError, match="POA-DOC-001"):
        bus.query({"schema": "subllm.query/v1", "process_uri": VALIDATE_URI, "shell": "rm -rf /"})


def test_unknown_uri_fails_closed() -> None:
    bus = PolicyBus()
    with pytest.raises(PoaContractError, match="POA-REGISTRY-001"):
        bus.query({"schema": "subllm.query/v1", "process_uri": "subllm://local/policy/query/invented"})


def test_create_plan_appends_secret_free_events() -> None:
    bus = PolicyBus()
    result = bus.command(
        {
            "schema": "subllm.command/v1",
            "process_uri": CREATE_PLAN_URI,
            "process_ref": LIST_ROUTES_REF,
            "input_ref": ROUTE_INPUT,
            "input_sha256": digest_document({"application": None}),
            "subject": "service:subllm-test",
            "idempotency_key": "test.plan.list-routes",
        }
    )
    events = bus.store.events(result["run_id"])
    assert [event["event_type"] for event in events] == ["planned"]
    assert all(event["secret_material_included"] is False for event in events)
    assert all(event["raw_output_included"] is False for event in events)
    assert "api_key" not in json.dumps(result)
    assert result["plan"]["execution_boundary"]["host_shell"] is False
    replay = bus.command(
        {
            "schema": "subllm.command/v1",
            "process_uri": CREATE_PLAN_URI,
            "process_ref": LIST_ROUTES_REF,
            "input_ref": ROUTE_INPUT,
            "input_sha256": digest_document({"application": None}),
            "subject": "service:subllm-test",
            "idempotency_key": "test.plan.list-routes",
        }
    )
    assert replay["idempotent"] is True
    assert replay["run_id"] == result["run_id"]
    assert bus.store.sequence == 1


def test_import_command_records_names_not_values(tmp_path: Path) -> None:
    source = tmp_path / "source.env"
    source.write_text("OPENROUTER_API_KEY=or-import-secret\n", encoding="utf-8")
    source.chmod(0o600)
    target = tmp_path / ".env"
    bus = PolicyBus()
    result = bus.command(
        {
            "schema": "subllm.command/v1",
            "process_uri": "subllm://local/policy/command/import-credentials",
            "sources": [str(source)],
            "target": str(target),
            "subject": "service:subllm-test",
            "idempotency_key": "test.import.credentials",
        }
    )
    payload = json.dumps(result)
    assert "or-import-secret" not in payload
    assert result["result"]["imported"] == ["OPENROUTER_API_KEY"]
    assert [event["event_type"] for event in bus.store.events(result["run_id"])] == [
        "planned",
        "started",
        "completed",
        "verified",
    ]
    observed = bus.query({"schema": "subllm.query/v1", "process_uri": LIST_ROUTES_URI})
    assert bus.store.sequence == 4
    assert observed["routes"]


def test_process_editor_returns_digest_bound_proposal_and_receipt() -> None:
    source = _editable_process()
    base_sha256 = digest_document(source)
    bus = PolicyBus()
    result = bus.command(
        {
            "schema": "subllm.command/v1",
            "process_uri": EDIT_PROCESS_URI,
            "source_process": source,
            "base_sha256": base_sha256,
            "edits": [
                {"op": "replace", "path": "/timeout_seconds", "value": 1200},
                {"op": "replace", "path": "/retry_policy/max_attempts", "value": 2},
            ],
            "subject": "agent:subllm-process-editor",
            "idempotency_key": "test.edit.repair-process",
        }
    )

    proposal = result["result"]
    assert proposal["authority"] == "proposal-only"
    assert proposal["base_sha256"] == base_sha256
    assert proposal["candidate_process"]["timeout_seconds"] == 1200
    assert proposal["candidate_process"]["retry_policy"]["max_attempts"] == 2
    assert proposal["candidate_sha256"] == digest_document(proposal["candidate_process"])
    assert result["plan"]["process_ref"] == EDIT_PROCESS_REF
    assert result["receipt"]["steps"][0]["output_sha256"] == proposal["candidate_sha256"]
    assert [event["event_type"] for event in bus.store.events(result["run_id"])] == [
        "planned",
        "started",
        "completed",
        "verified",
    ]

    replay = bus.command(
        {
            "schema": "subllm.command/v1",
            "process_uri": EDIT_PROCESS_URI,
            "source_process": source,
            "base_sha256": base_sha256,
            "edits": [{"op": "replace", "path": "/timeout_seconds", "value": 99}],
            "subject": "agent:subllm-process-editor",
            "idempotency_key": "test.edit.repair-process",
        }
    )
    assert replay["idempotent"] is True
    assert replay["run_id"] == result["run_id"]


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda source: "a" * 64, "POA-EDIT-002"),
        (
            lambda source: digest_document(
                {
                    **source,
                    "decision_policy": {
                        **source["decision_policy"],
                        "llm_editor": {
                            **source["decision_policy"]["llm_editor"],
                            "editable_paths": ["/allowed_actions"],
                        },
                    },
                }
            ),
            "POA-EDIT-003",
        ),
    ],
)
def test_process_editor_rejects_stale_base_and_authority_edits(mutate, code: str) -> None:
    source = _editable_process()
    if code == "POA-EDIT-003":
        source["decision_policy"]["llm_editor"]["editable_paths"] = ["/allowed_actions"]
        edits = [{"op": "replace", "path": "/allowed_actions", "value": ["arbitrary_shell"]}]
    else:
        edits = [{"op": "replace", "path": "/timeout_seconds", "value": 1200}]
    with pytest.raises(PoaContractError, match=code):
        PolicyBus().command(
            {
                "schema": "subllm.command/v1",
                "process_uri": EDIT_PROCESS_URI,
                "source_process": source,
                "base_sha256": mutate(source),
                "edits": edits,
                "subject": "agent:subllm-process-editor",
                "idempotency_key": f"test.edit.reject.{code.lower()}",
            }
        )


def test_process_editor_rejects_secret_before_appending_events() -> None:
    source = _editable_process()
    source["token"] = "must-not-enter-the-journal"
    bus = PolicyBus()
    with pytest.raises(PoaContractError, match="POA-SECRET-001"):
        bus.command(
            {
                "schema": "subllm.command/v1",
                "process_uri": EDIT_PROCESS_URI,
                "source_process": source,
                "base_sha256": digest_document(source),
                "edits": [{"op": "replace", "path": "/timeout_seconds", "value": 1200}],
                "subject": "agent:subllm-process-editor",
                "idempotency_key": "test.edit.secret",
            }
        )
    assert bus.store.events() == []


def test_adopted_poa_catalog_matches_exporter() -> None:
    adopted = json.loads((ROOT / "policy" / "adopted" / "poa" / "process-catalog.json").read_text(encoding="utf-8"))
    catalog = catalog_document()
    assert adopted["home"] == "subactor"
    assert adopted["shape"] == "runtime_service"
    assert adopted["uris"] == catalog["uris"]
    assert [item["process_ref"] for item in adopted["processes"]] == [
        item["process_ref"] for item in catalog["processes"]
    ]


def test_event_store_rejects_secret_flags() -> None:
    store = EventStore()
    with pytest.raises(PoaContractError, match="POA-EVENT-001"):
        store.append(
            {
                "schema": "poa.event/v1",
                "event_id": "evt.pending",
                "run_id": "run.test",
                "sequence": 0,
                "process_ref": VALIDATE_REF,
                "plan_ref": "sha256:" + "a" * 64,
                "event_type": "planned",
                "occurred_at": "2026-08-19T16:00:00Z",
                "artifact_refs": [],
                "raw_output_included": False,
                "secret_material_included": True,
            }
        )
