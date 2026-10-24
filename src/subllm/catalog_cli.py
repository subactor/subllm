"""Schema-aware catalog proposals: export, schema, check, propose.

Use ``python -m subllm.catalog_cli --help``. Activation is separate: set
SUBLLM_CATALOG_FILE to an absolute reviewed JSON/TOML file and
SUBLLM_CATALOG_SHA256 to its independently accepted raw-file digest before
starting a process. The CLI never sets these variables or modifies a service.
Legacy defaults and runtime TOML remain compatible for the migration release.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path

from .catalog import canonical, compile_catalog, export_catalog, read_document
from .catalog_schema import schema
from .errors import InvalidPolicyError


def propose(document, operations, expected_sha256):
    base = compile_catalog(document)
    if expected_sha256 != base.sha256:
        raise InvalidPolicyError("catalog proposal base digest mismatch")
    if not isinstance(operations, list) or not 1 <= len(operations) <= 32:
        raise InvalidPolicyError("catalog proposal requires 1..32 operations")
    candidate = copy.deepcopy(document)
    for operation in operations:
        if (not isinstance(operation, dict) or not isinstance(operation.get("op"), str)
                or operation["op"] not in {"add", "replace", "remove"}):
            raise InvalidPolicyError("invalid catalog proposal operation")
        required = {"op", "path"} | (set() if operation["op"] == "remove" else {"value"})
        path = operation.get("path")
        if (set(operation) != required or not isinstance(path, list) or not 1 <= len(path) <= 8
                or any(not ((isinstance(p, str) and 1 <= len(p) <= 128)
                            or (type(p) is int and 0 <= p < 4096)) for p in path)):
            raise InvalidPolicyError("invalid catalog proposal path")
        try:
            parent = candidate
            for part in path[:-1]:
                if not isinstance(parent, (dict, list)):
                    raise KeyError
                parent = parent[part]
            key = path[-1]
            if isinstance(parent, dict):
                exists = key in parent
            elif isinstance(parent, list) and type(key) is int:
                exists = key < len(parent)
            else:
                raise KeyError
            if operation["op"] in {"replace", "remove"} and not exists:
                raise KeyError
            if operation["op"] == "add":
                if isinstance(parent, list):
                    if key > len(parent):
                        raise KeyError
                    parent.insert(key, copy.deepcopy(operation["value"]))
                else:
                    if exists:
                        raise KeyError
                    parent[key] = copy.deepcopy(operation["value"])
            elif operation["op"] == "remove":
                del parent[key]
            else:
                parent[key] = copy.deepcopy(operation["value"])
        except (KeyError, IndexError, TypeError):
            raise InvalidPolicyError("catalog proposal path or operation is inconsistent") from None
    compiled = compile_catalog(candidate)
    if compiled.sha256 == base.sha256:
        raise InvalidPolicyError("catalog proposal has no semantic change")
    return candidate, {"schema": "subllm.catalog-proposal/v1", "authority": "none",
                       "base_sha256": base.sha256, "catalog_sha256": compiled.sha256}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("schema")
    commands.add_parser("export")
    check = commands.add_parser("check")
    check.add_argument("file", type=Path)
    edit = commands.add_parser("propose")
    edit.add_argument("file", type=Path)
    edit.add_argument("--operations", required=True, type=Path)
    edit.add_argument("--expected-sha256", required=True)
    edit.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "schema":
            result = schema()
        elif args.command == "export":
            result = export_catalog()
        else:
            document, source_hash = read_document(args.file)
            compiled = compile_catalog(document)
            result = {"schema": "subllm.catalog-check/v1", "authority": "none", "valid": True,
                      "source_sha256": source_hash, "catalog_sha256": compiled.sha256}
            if args.command == "propose":
                operations, _ = read_document(args.operations, maximum=65536)
                candidate, result = propose(document, operations, args.expected_sha256)
                output = args.output
                if (not output.is_absolute() or ".." in output.parts
                        or any(p.is_symlink() for p in (output, *output.parents))):
                    raise InvalidPolicyError("catalog proposal output must be a new absolute regular path")
                raw = (canonical(candidate) + "\n").encode()
                fd = os.open(output, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                except BaseException:
                    output.unlink(missing_ok=True)
                    raise
                result["source_sha256"] = hashlib.sha256(raw).hexdigest()
        print(json.dumps(result, sort_keys=True, allow_nan=False))
        return 0
    except (InvalidPolicyError, OSError, ValueError, TypeError, RecursionError):
        print(json.dumps({"schema": "subllm.catalog-result/v1", "status": "invalid", "authority": "none"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
