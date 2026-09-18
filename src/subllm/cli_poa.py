from __future__ import annotations

import argparse
from uuid import uuid4

from .cli_policy import _print_json, _query
from .poa.bus import PolicyBus
from .poa.canonical import digest_document
from .poa.http import serve
from .poa.refs import ROUTE_INPUT
from .poa.registry import CREATE_PLAN_URI, catalog_document


def _run_poa(bus: PolicyBus, args: argparse.Namespace) -> int:
    if args.poa_command == "catalog":
        _print_json(catalog_document())
        return 0
    if args.poa_command == "inspect":
        _print_json(bus.inspect(args.process_ref))
        return 0
    if args.poa_command == "query":
        _print_json(
            _query(
                bus,
                args.process_uri,
                application=args.application,
                function=args.function,
                provider=args.provider,
                run_id=args.run_id,
            )
        )
        return 0
    input_doc = {
        "application": getattr(args, "application", None),
        "function": getattr(args, "function", None),
        "provider": getattr(args, "provider", None),
    }
    command: dict[str, object] = {
        "schema": "subllm.command/v1",
        "process_uri": CREATE_PLAN_URI if args.poa_command == "plan" else args.process_uri,
        "subject": args.subject,
        "idempotency_key": args.idempotency_key or f"cli.{args.poa_command}.{uuid4().hex[:12]}",
    }
    process_ref = args.process_ref if args.poa_command == "plan" else getattr(args, "process_ref", None)
    if process_ref:
        command["process_ref"] = process_ref
        command["input_ref"] = ROUTE_INPUT
        command["input_sha256"] = digest_document(input_doc)
    if args.poa_command == "command" and args.sources:
        command["sources"] = list(args.sources)
        command["target"] = args.target or ".env"
    _print_json(bus.command(command))
    return 0


def _run_serve(bus: PolicyBus, args: argparse.Namespace) -> int:
    serve(host=args.host, port=args.port, bus=bus)
    return 0
