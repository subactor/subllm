"""Wellmanifest Logs 0.5 operational projection. Contains no prompt or reply."""

import hashlib
import json


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def make_event(record, sequence, previous_hash):
    done = record["finished_at"] is not None
    info = record.get("diagnostic")
    event = {
        "schema": "wellmanifest.logs/event/v1",
        "eventId": f"event:{record['id']}:{sequence}",
        "stream": "subllm.gateway." + record["day"],
        "sequence": sequence,
        "eventType": "error_raised"
        if info
        else "subllm.interaction_completed"
        if done
        else "subllm.interaction_started",
        "severity": "ERROR" if info else "INFO",
        "mode": "APPLY",
        "occurredAt": record["finished_at"] or record["started_at"],
        "correlationId": record["correlation_id"],
        "causationId": record["id"],
        "producer": "service:subllm-gateway",
        "source": "subllm.gateway",
        "code": info["code"] if info else None,
        "subjectRef": f"interaction://subllm/{record['day']}/{record['id']}",
        "outcome": "FAILED" if info else "SUCCEEDED" if done else "OBSERVED",
        "subjectState": record["status"],
        "evidence": [],
        "inputHash": hashlib.sha256(record["id"].encode()).hexdigest(),
        "receiptRef": None,
        "previousHash": previous_hash,
        "rawOutputIncluded": False,
        "secretMaterialIncluded": False,
    }
    if info:
        event["diagnostic"] = {
            k: info[k]
            for k in (
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
            )
        }
    event["eventHash"] = hashlib.sha256(canonical(event).encode()).hexdigest()
    return event
