from __future__ import annotations

import argparse
import getpass
import sys
from uuid import uuid4

from . import credential_store as store
from .cli_policy import _query
from .credential_env import load_env_file
from .credential_template import PRESETS, render
from .errors import CredentialFileError, SubLLMError
from .poa.bus import PolicyBus
from .poa.registry import IMPORT_CREDENTIALS_URI, OBSERVE_CREDENTIALS_URI


def _read_key(args: argparse.Namespace) -> str:
    if args.from_file:
        tokens = args.from_file.read_text(encoding="utf-8").split()
        if len(tokens) != 1:
            raise CredentialFileError("the key file must contain exactly one token")
        return tokens[0]
    if args.stdin:
        return sys.stdin.readline().strip()
    if not sys.stdin.isatty():
        raise CredentialFileError("no terminal for a hidden prompt; use --stdin or --from-file")
    return getpass.getpass(f"Key for {args.name} (input hidden): ").strip()


def _run_keys(args: argparse.Namespace) -> int:
    command = args.env_command
    if command == "template":
        print(render(), end="")
        return 0
    path = store.resolve_target(getattr(args, "file", None))
    if command == "list":
        print(f"file: {path}")
        for item in store.describe(path):
            print(f"{item.variable:20} {item.state:8} providers={','.join(item.providers) or '-'}"
                  + (f" length={item.length}" if item.length else ""))
        return 0
    if command == "order":
        if args.preset:
            if args.preset not in PRESETS:
                raise CredentialFileError(f"unknown preset {args.preset!r}; known: {', '.join(PRESETS)}")
            args.order = PRESETS[args.preset][0]
        if args.order is not None:
            backup = store.set_order(path, args.order)
            print(f"order set; backup: {backup}" if backup else "order set")
        print(f"current: {store.current_order(path) or '(empty: subllm.toml priorities)'}")
        for name, (order, note) in PRESETS.items():
            print(f"  preset {name:17} {order}   # {note}")
        return 0
    if command == "unset":
        variable = store.variable_for(args.name)
        backup = store.unset_value(path, variable)
        print(f"{variable} cleared; backup: {backup}")
        return 0
    if command == "verify":
        values = load_env_file(path)
        names = [store.variable_for(n) for n in args.names] or [
            v for v, value in values.items() if value and v in store.credential_names()]
        failed = False
        for variable in names:
            result = store.verify_key(variable, values.get(variable, ""))
            print(f"{variable:20} {result.status:12} {result.detail}")
            failed = failed or result.status in {"invalid", "missing"}
        return 1 if failed else 0
    variable = store.variable_for(args.name)  # command == "set"
    key = _read_key(args)
    if not args.no_verify:
        result = store.verify_key(variable, key)
        print(f"{variable}: {result.status}: {result.detail}")
        if result.status in {"invalid"}:
            raise CredentialFileError("the provider rejected this key; nothing was written")
    backup = store.set_value(path, variable, key)
    print(f"{variable} stored in {path}" + (f"; backup: {backup}" if backup else ""))
    return 0


def _run_env(bus: PolicyBus, args: argparse.Namespace) -> int:
    if args.env_command in {"list", "set", "unset", "verify", "order", "template"}:
        return _run_keys(args)
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
