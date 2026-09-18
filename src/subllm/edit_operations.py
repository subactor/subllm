"""Low-level validation and atomic path/json operations for edit plan."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .code_context import encode, safe_path
from .edit_schema import MAX_CHANGE_BYTES
from .errors import CompletionError


def _text(value: object) -> str:
    if not isinstance(value, str) or "\0" in value or len(value.encode()) > MAX_CHANGE_BYTES:
        raise CompletionError("edit plan text exceeds boundary")
    return value


def _creation_path(root: Path, name: str, environ: dict) -> Path:
    file = safe_path(root, name)
    if file.exists():
        raise CompletionError("edit plan creation target already exists")
    # Git interprets the operator's ignore patterns; these are policy, not prompt inference.
    policies = [None, ".dockerignore", ".intentignore", environ.get("AIDER_AIDERIGNORE") or ".aiderignore"]
    for policy in policies:
        command = ["git"]
        if policy:
            ignore = Path(policy)
            if not ignore.is_absolute():
                ignore = root / ignore
            if any(p.is_symlink() for p in [ignore, *ignore.parents]):
                raise CompletionError("edit plan ignore policy contains a symlink")
            if not ignore.is_file():
                continue
            command += ["-c", f"core.excludesFile={ignore}"]
        result = subprocess.run(
            [*command, "check-ignore", "--no-index", "--", name], cwd=root, capture_output=True, timeout=10
        )
        if result.returncode != 1:
            raise CompletionError("edit plan creation path is ignored or cannot be verified")
    return file


def _json_update(document: object, pointer: object, value: object, field: str) -> None:
    if not isinstance(pointer, list) or not pointer or pointer[0] != field:
        raise CompletionError("JSON update is outside selected configuration field")
    current = document
    for key in pointer[:-1]:
        if not isinstance(current, dict) or not isinstance(key, str) or key not in current:
            raise CompletionError("JSON update parent does not exist")
        current = current[key]
    if not isinstance(current, dict) or not isinstance(pointer[-1], str):
        raise CompletionError("JSON update requires an object property")
    if len(encode(value).encode()) > MAX_CHANGE_BYTES:
        raise CompletionError("JSON update exceeds boundary")
    current[pointer[-1]] = value
