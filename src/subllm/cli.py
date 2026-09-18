from __future__ import annotations

import argparse
from collections.abc import Sequence

from .cli_env import _run_env
from .cli_parser import _parser
from .cli_poa import _run_poa, _run_serve
from .cli_policy import _run_policy_query, _run_resolve
from .errors import SubLLMError
from .poa.bus import PolicyBus


def dispatch(bus: PolicyBus, args: argparse.Namespace) -> int:
    if args.command in ("check", "contract", "list", "providers", "applications"):
        return _run_policy_query(bus, args)
    if args.command == "env":
        return _run_env(bus, args)
    if args.command == "poa":
        return _run_poa(bus, args)
    if args.command == "serve":
        return _run_serve(bus, args)
    if args.command == "proxy":
        from .proxy import serve_proxy
        serve_proxy(host=args.host, port=args.port, ollama_upstream=args.ollama_upstream)
        return 0
    return _run_resolve(bus, args)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    bus = PolicyBus()
    try:
        return dispatch(bus, args)
    except SubLLMError as exc:
        print(f"subllm: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
