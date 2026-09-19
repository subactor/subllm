"""Gateway PolicyBus boundary. POA events contain references, never private bodies."""

from __future__ import annotations

import threading

from .poa.bus import PolicyBus
from .poa.registry import GATEWAY_EXCHANGE_URI
from .poa.store import EventStore


class GatewayEventStore(EventStore):
    def append(self, event):
        result = super().append(event)
        # Durable events live in the interaction store; bound the control-plane memory window.
        del self._events[:-1024]
        return result


class GatewayPolicyBus(PolicyBus):
    def __init__(self, interaction_store, *args, **kwargs):
        if not args and "store" not in kwargs:
            kwargs["store"] = GatewayEventStore()
        super().__init__(*args, **kwargs)
        self.interactions = interaction_store
        self.gateway_lock = threading.Lock()

    def record_gateway_exchange(self, record):
        with self.gateway_lock:
            return self.command(
                {
                    "schema": "subllm.command/v1",
                    "process_uri": GATEWAY_EXCHANGE_URI,
                    "subject": "service:subllm-gateway",
                    "idempotency_key": "gateway." + record["id"],
                    "interaction_ref": record["day"] + "/" + record["id"],
                }
            )

    def interaction_query(self, *, day, record_id=None, caller=None, read_all=False, **filters):
        # This deliberately private read model is not exposed through the public policy API.
        if record_id:
            result = self.interactions.query(day, record_id)
            return result if result and (read_all or result["caller"] == caller) else None
        return self.interactions.query(day, caller=None if read_all else caller, **filters)
