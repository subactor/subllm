from __future__ import annotations

import argparse
from uuid import uuid4

from .cli_policy import _query
from .errors import SubLLMError
from .poa.bus import PolicyBus
from .poa.registry import IMPORT_CREDENTIALS_URI, OBSERVE_CREDENTIALS_URI


def _run_env(bus: PolicyBus, args: argparse.Namespace) -> int:
    if args.env_command == "import":
        result = bus.command(
            {
                "schema": "subllm.command/v1",
                "process_uri": IMPORT_CREDENTIALS_URI,
                "sources": [str(path) for path in args.sources],
                "target": str(args.target),
                "subject": "service:subllm-cli",
                "idempotency_key": f"cli.import.{uuid4().hex[:12]}",
            }
        )
        imported = ", ".join(result["result"]["imported"])
        print(f"Imported {imported} into {args.target.resolve(strict=False)}")
        return 0
    observed = _query(bus, OBSERVE_CREDENTIALS_URI)
    if observed["path"] is None:
        raise SubLLMError("shared credential file not found; create subllm/.env from .env.example")
    if args.env_command == "path":
        print(observed["path"])
        return 0
    for name, state in observed["credentials"].items():
        print(f"{name}: {state}")
    return 0
