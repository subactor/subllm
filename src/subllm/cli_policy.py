from __future__ import annotations

import argparse
import json
from collections.abc import Mapping

from .poa.bus import PolicyBus
from .poa.registry import (
    CONFIGURED_ROUTE_URI,
    EXPORT_CONTRACT_URI,
    LIST_APPLICATIONS_URI,
    LIST_PROVIDERS_URI,
    LIST_ROUTES_URI,
    RESOLVE_ROUTE_URI,
    VALIDATE_URI,
)


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _field(route: Mapping[str, object], name: str) -> object:
    return route[name.replace("-", "_")]


def _query(bus: PolicyBus, process_uri: str, **fields: object) -> dict[str, object]:
    document: dict[str, object] = {"schema": "subllm.query/v1", "process_uri": process_uri}
    document.update({key: value for key, value in fields.items() if value not in (None, "")})
    return bus.query(document)


def _run_policy_query(bus: PolicyBus, args: argparse.Namespace) -> int:
    if args.command == "check":
        _query(bus, VALIDATE_URI)
        print("SubLLM policy: OK")
        return 0
    if args.command == "contract":
        _print_json(_query(bus, EXPORT_CONTRACT_URI, application=args.application, function=args.function))
        return 0
    if args.command == "list":
        _print_json(_query(bus, LIST_ROUTES_URI)["routes"])
        return 0
    if args.command == "providers":
        _print_json(_query(bus, LIST_PROVIDERS_URI))
        return 0
    _print_json(_query(bus, LIST_APPLICATIONS_URI))
    return 0


def _run_resolve(bus: PolicyBus, args: argparse.Namespace) -> int:
    process_uri = CONFIGURED_ROUTE_URI if args.configured else RESOLVE_ROUTE_URI
    route = _query(bus, process_uri, application=args.application, function=args.function, provider=args.provider)
    if args.field:
        print(_field(route, args.field))
    else:
        _print_json(route)
    return 0
