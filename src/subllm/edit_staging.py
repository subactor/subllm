"""Assembly, syntax verification and re-observation of staged edit content."""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path

from .code_context import CodeContext, safe_path
from .edit_operations import _creation_path
from .errors import CompletionError


def _stage_replacements(
    replacements: dict[str, list[tuple[int, int, str]]],
    context: CodeContext,
    json_documents: dict[str, object],
) -> dict[str, bytes]:
    staged = {}
    for name, spans in replacements.items():
        if name in json_documents:
            raise CompletionError("cannot mix JSON and text operations on one file")
        ordered = sorted(spans)
        if any(a[1] > b[0] for a, b in zip(ordered, ordered[1:], strict=False)):
            raise CompletionError("edit plan ranges overlap")
        body = context.sources[name].decode()
        for start, end, replacement in reversed(ordered):
            body = body[:start] + replacement + body[end:]
        staged[name] = body.encode()
    return staged


def _verify_staged_content(staged: dict[str, bytes], creates: dict[str, bytes], context: CodeContext) -> None:
    if sum(len(data) for data in creates.values()) > 1_048_576:
        raise CompletionError("creation batch exceeds budget")
    for name, data in staged.items():
        try:
            if name.endswith(".py"):
                ast.parse(data, filename=name)
            elif name.endswith(".json"):
                json.loads(data)
            elif name.endswith(".toml"):
                tomllib.loads(data.decode())
        except (ValueError, SyntaxError) as exc:
            raise CompletionError("edit plan produced invalid document syntax") from exc
        if name not in creates and data == context.sources[name]:
            raise CompletionError("edit plan made no material change")


def _reobserve(
    root: Path, staged: dict[str, bytes], creates: dict[str, bytes], context: CodeContext, environ: dict
) -> None:
    for name in staged:
        if name in creates:
            _creation_path(root, name, environ)
        elif safe_path(root, name).read_bytes() != context.sources[name]:
            raise CompletionError("edit plan source changed before apply")
