from __future__ import annotations

from copy import deepcopy
from typing import Any

from .errors import PoaContractError

EVENT_TYPES = {
    "requested",
    "planned",
    "authorized",
    "started",
    "completed",
    "verified",
    "failed",
    "denied",
}


class EventStore:
    """In-memory event-sourced journal. Queries never write through this store."""

    def __init__(self) -> None:
        self._events: list[dict[str, Any]] = []
        self._receipts: dict[str, dict[str, Any]] = {}
        self._plans: dict[str, dict[str, Any]] = {}
        self._idempotency: dict[str, str] = {}
        self.sequence = 0

    def events(self, run_id: str | None = None) -> list[dict[str, Any]]:
        if run_id is None:
            return [deepcopy(event) for event in self._events]
        return [deepcopy(event) for event in self._events if event["run_id"] == run_id]

    def receipt(self, run_id: str) -> dict[str, Any] | None:
        receipt = self._receipts.get(run_id)
        return deepcopy(receipt) if receipt is not None else None

    def plan(self, run_id: str) -> dict[str, Any] | None:
        plan = self._plans.get(run_id)
        return deepcopy(plan) if plan is not None else None

    def run_for_idempotency(self, key: str) -> str | None:
        return self._idempotency.get(key)

    def remember_plan(self, run_id: str, plan: dict[str, Any], idempotency_key: str) -> None:
        self._plans[run_id] = deepcopy(plan)
        self._idempotency[idempotency_key] = run_id

    def remember_receipt(self, run_id: str, receipt: dict[str, Any]) -> None:
        self._receipts[run_id] = deepcopy(receipt)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        if event.get("schema") != "poa.event/v1":
            raise PoaContractError("POA-EVENT-001", "event schema is not registered")
        if event.get("event_type") not in EVENT_TYPES:
            raise PoaContractError("POA-EVENT-001", "event type is not registered")
        if event.get("raw_output_included") is not False or event.get("secret_material_included") is not False:
            raise PoaContractError("POA-EVENT-001", "event must not carry raw output or secrets")
        self.sequence += 1
        stored = deepcopy(event)
        stored["sequence"] = self.sequence
        stored["event_id"] = f"evt.{self.sequence:06d}"
        self._events.append(stored)
        return deepcopy(stored)
