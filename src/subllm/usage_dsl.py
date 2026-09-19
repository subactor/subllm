"""Bounded read-only NL/DSL intake shared by CLI, HTTP and MCP."""

from __future__ import annotations

import re
import shlex
from typing import Any

from .poa.bus import PolicyBus
from .poa.errors import PoaContractError
from .poa.registry import USAGE_URI
from .usage import FILTERS


def grammar() -> dict[str, Any]:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "command": {"const": "usage.list"},
            "filters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {key: {"type": "string"} for key in sorted(FILTERS)},
            },
        },
        "required": ["command"],
        "examples": ["usage.list", "usage.list provider=zai limit=20", "pokaż logi z.ai", "show api usage"],
        "description": "Read-only usage.list [application=ID] [provider=ID] [status=success|error] "
        "[since=RFC3339] [until=RFC3339] [limit=1..500] [before=ID]. "
        "Unknown NL fails closed; no model calls or mutations.",
    }


def execute(command: str, bus: PolicyBus) -> dict[str, Any]:
    if not isinstance(command, str) or len(command) > 2048:
        raise PoaContractError("USAGE-DSL-001", "Expected a bounded usage.list command")
    try:
        words = shlex.split(command)
    except ValueError as exc:
        raise PoaContractError("USAGE-DSL-001", "Invalid DSL quoting") from exc
    if not words or words[0] != "usage.list":
        raise PoaContractError("USAGE-DSL-001", "Only usage.list is supported")
    filters = {}
    for word in words[1:]:
        key, sep, value = word.partition("=")
        if not sep or key not in FILTERS or key in filters or not value:
            raise PoaContractError("USAGE-DSL-001", "Invalid or duplicate filter")
        filters[key] = value
    data = bus.query({"schema": "subllm.query/v1", "process_uri": USAGE_URI, **filters})
    return {"success": True, "command": "usage.list", "status": "COMPLETED", "data": data, "errors": []}


def ask(question: str, bus: PolicyBus) -> dict[str, Any]:
    if not isinstance(question, str) or len(question) > 2048:
        raise PoaContractError("USAGE-NL-001", "Expected a bounded question")
    match = re.fullmatch(
        r"(?:pokaż|pokaz|wyświetl|wyswietl|show|list)\s+(?:logi(?:\s+api)?|użycie\s+api|api\s+usage|logs)"
        r"(?:\s+(z\.ai|zai|openrouter|(?:[a-z_]+=[^\s]+)(?:\s+[a-z_]+=[^\s]+)*))?",
        question.strip(),
        re.IGNORECASE,
    )
    if not match:
        raise PoaContractError("USAGE-NL-001", "Unknown question; use usage.list or describe_grammar")
    suffix = match.group(1) or ""
    if suffix.lower() in {"z.ai", "zai", "openrouter"}:
        suffix = "provider=" + ("zai" if suffix.lower() != "openrouter" else "openrouter")
    return execute("usage.list " + suffix, bus)
