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
    LIST_ROUTES_REF,
    LIST_ROUTES_URI,
    VALIDATE_REF,
    VALIDATE_URI,
)

ROOT = Path(__file__).resolve().parents[1]


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
