from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .policy import ROUTES
from .resolver import SubLLMError, configured_route, configured_routes, resolve, validate_policy


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="subllm", description="Inspect the central Subactor LLM policy.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="validate the built-in policy")
    subparsers.add_parser("list", help="list application/function routes")
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
        choices=("provider", "model", "priority", "api-base", "api-key-env", "litellm-model", "wire-model"),
    )
    return parser


def _field(route: object, name: str) -> object:
    return getattr(route, name.replace("-", "_"))


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "check":
            validate_policy()
            print("SubLLM policy: OK")
            return 0
        if args.command == "list":
            payload = []
            for application, function in sorted(ROUTES):
                payload.append(
                    {
                        "application": application,
                        "function": function,
                        "candidates": [route.public_dict() for route in configured_routes(application, function)],
                    }
                )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        if args.configured:
            route = configured_route(args.application, args.function, provider=args.provider)
        else:
            route = resolve(args.application, args.function, provider=args.provider)
        if args.field:
            print(_field(route, args.field))
        else:
            print(json.dumps(route.public_dict(), indent=2, sort_keys=True))
        return 0
    except SubLLMError as exc:
        print(f"subllm: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

