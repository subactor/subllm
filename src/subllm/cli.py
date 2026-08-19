from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from uuid import uuid4

from .errors import SubLLMError
from .poa.bus import PolicyBus
from .poa.canonical import digest_document
from .poa.http import serve
from .poa.refs import ROUTE_INPUT
from .poa.registry import (
    CONFIGURED_ROUTE_URI,
    CREATE_PLAN_URI,
    IMPORT_CREDENTIALS_URI,
    LIST_APPLICATIONS_URI,
    LIST_PROVIDERS_URI,
    LIST_ROUTES_URI,
    OBSERVE_CREDENTIALS_URI,
    RESOLVE_ROUTE_URI,
    VALIDATE_URI,
    catalog_document,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="subllm", description="Inspect the central Subactor LLM policy.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="validate the effective policy")
    subparsers.add_parser("list", help="list application/function routes")
    subparsers.add_parser("providers", help="show enabled state, priority and default model")
    subparsers.add_parser("applications", help="show application IDs, names and attribution URLs")
    env_parser = subparsers.add_parser("env", help="inspect or initialize the shared local credential file")
    env_subparsers = env_parser.add_subparsers(dest="env_command", required=True)
    env_subparsers.add_parser("path", help="print the detected credential file path")
    env_subparsers.add_parser("check", help="validate the file and print configured variable names")
    import_parser = env_subparsers.add_parser("import", help="import credentials from existing .env files")
    import_parser.add_argument("sources", nargs="+", type=Path)
    import_parser.add_argument("--target", type=Path, default=Path(".env"))
    resolve_parser = subparsers.add_parser("resolve", help="resolve one application/function route")
    resolve_parser.add_argument("application")
    resolve_parser.add_argument("function")
    resolve_parser.add_argument("--provider")
    resolve_parser.add_argument(
        "--configured",
        action="store_true",
        help="inspect policy without requiring a credential",
    )
    resolve_parser.add_argument(
        "--field",
        choices=(
            "application-name",
            "application-url",
            "provider",
            "model",
            "priority",
            "api-base",
            "api-key-env",
            "litellm-model",
            "wire-model",
        ),
    )
    poa = subparsers.add_parser("poa", help="POA inspect, plan, query and command surface")
    poa_sub = poa.add_subparsers(dest="poa_command", required=True)
    inspect = poa_sub.add_parser("inspect", help="inspect a declared process")
    inspect.add_argument("process_ref")
    plan = poa_sub.add_parser("plan", help="create a secret-free dry plan")
    plan.add_argument("process_ref")
    plan.add_argument("--application")
    plan.add_argument("--function")
    plan.add_argument("--provider")
    plan.add_argument("--subject", default="service:subllm-cli")
    plan.add_argument("--idempotency-key")
    query = poa_sub.add_parser("query", help="run a registered query URI")
    query.add_argument("process_uri")
    query.add_argument("--application")
    query.add_argument("--function")
    query.add_argument("--provider")
    query.add_argument("--run-id")
    command = poa_sub.add_parser("command", help="run a registered command URI")
    command.add_argument("process_uri")
    command.add_argument("--process-ref")
    command.add_argument("--application")
    command.add_argument("--function")
    command.add_argument("--provider")
    command.add_argument("--subject", default="service:subllm-cli")
    command.add_argument("--idempotency-key")
    command.add_argument("--source", action="append", dest="sources")
    command.add_argument("--target")
    poa_sub.add_parser("catalog", help="print the adopted process catalog")
    serve_parser = subparsers.add_parser("serve", help="serve the local POA CQRS HTTP API")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8788)
    return parser


def _field(route: Mapping[str, object], name: str) -> object:
    return route[name.replace("-", "_")]


def _print_json(payload: object) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _query(bus: PolicyBus, process_uri: str, **fields: object) -> dict[str, object]:
    document: dict[str, object] = {"schema": "subllm.query/v1", "process_uri": process_uri}
    document.update({key: value for key, value in fields.items() if value not in (None, "")})
    return bus.query(document)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bus = PolicyBus()
    try:
        if args.command == "check":
            _query(bus, VALIDATE_URI)
            print("SubLLM policy: OK")
            return 0
        if args.command == "list":
            _print_json(_query(bus, LIST_ROUTES_URI)["routes"])
            return 0
        if args.command == "providers":
            _print_json(_query(bus, LIST_PROVIDERS_URI))
            return 0
        if args.command == "applications":
            _print_json(_query(bus, LIST_APPLICATIONS_URI))
            return 0
        if args.command == "env":
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
        if args.command == "poa":
            return _poa(bus, args)
        if args.command == "serve":
            serve(host=args.host, port=args.port, bus=bus)
            return 0
        process_uri = CONFIGURED_ROUTE_URI if args.configured else RESOLVE_ROUTE_URI
        route = _query(bus, process_uri, application=args.application, function=args.function, provider=args.provider)
        if args.field:
            print(_field(route, args.field))
        else:
            _print_json(route)
        return 0
    except SubLLMError as exc:
        print(f"subllm: {exc}")
        return 2


def _poa(bus: PolicyBus, args: argparse.Namespace) -> int:
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


if __name__ == "__main__":
    raise SystemExit(main())
