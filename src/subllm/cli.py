from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from .credential_env import credential_names, find_env_file, import_credentials, load_env_file
from .errors import SubLLMError
from .policy import ROUTES
from .policy_config import load_policy_config
from .provider_order import provider_order
from .resolver import configured_route, configured_routes, resolve, validate_policy


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
        if args.command == "providers":
            policy = load_policy_config()
            payload = {
                "source": str(policy.source) if policy.source is not None else "built-in defaults",
                "order": list(provider_order()),
                "providers": {name: asdict(settings) for name, settings in policy.providers.items()},
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        if args.command == "applications":
            policy = load_policy_config()
            payload = {
                "source": str(policy.source) if policy.source is not None else "built-in defaults",
                "applications": {name: asdict(settings) for name, settings in policy.applications.items()},
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        if args.command == "env":
            if args.env_command == "import":
                names = import_credentials(args.sources, args.target)
                print(f"Imported {', '.join(names)} into {args.target.resolve(strict=False)}")
                return 0
            path = find_env_file()
            if path is None:
                raise SubLLMError("shared credential file not found; create subllm/.env from .env.example")
            if args.env_command == "path":
                print(path)
                return 0
            configured = load_env_file(path)
            for name in credential_names():
                state = "configured" if configured.get(name) else "missing"
                print(f"{name}: {state}")
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
