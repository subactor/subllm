"""Envelope, evidence binding and operation interpretation for untrusted edit plans."""

from __future__ import annotations

import json
from pathlib import Path

from .code_context import CodeContext, digest
from .edit_operations import _creation_path, _json_update, _text
from .edit_schema import SCHEMA
from .errors import CompletionError


def _validate_envelope(answer: dict) -> None:
    required = {"schema", "summary", "edits", "patches", "creates", "json_updates"}
    if set(answer) != required or answer["schema"] != SCHEMA or not isinstance(answer["summary"], str):
        raise CompletionError("invalid edit plan v2 envelope")
    groups = [answer[k] for k in ("edits", "patches", "creates", "json_updates")]
    if any(not isinstance(g, list) for g in groups) or not 1 <= sum(map(len, groups)) <= 32:
        raise CompletionError("edit plan requires 1 to 32 operations")


def _bind_operation(
    operation: dict, keys: set[str], records: dict[str, dict], context: CodeContext
) -> tuple[dict, str, str]:
    if (
        not isinstance(operation, dict)
        or set(operation) != keys
        or not isinstance(operation.get("id"), str)
        or operation["id"] not in records
    ):
        raise CompletionError("edit plan references an unselected record")
    record = records[operation["id"]]
    name = record["source"]["path"]
    if operation["file_sha256"] != digest(context.sources[name]):
        raise CompletionError("edit plan source digest mismatch")
    return record, name, context.sources[name].decode()


def _process_edits(
    edits: list[dict],
    records: dict[str, dict],
    context: CodeContext,
    replacements: dict[str, list[tuple[int, int, str]]],
) -> None:
    for operation in edits:
        record, name, body = _bind_operation(operation, {"id", "file_sha256", "replacement"}, records, context)
        if not record.get("editable"):
            raise CompletionError("range replacement requires complete node evidence")
        lines = body.splitlines(keepends=True)
        span = record["source"]["lines"]
        start, end = span["start"], span["end"]
        if not 1 <= start <= end <= len(lines):
            raise CompletionError("edit plan range exceeds source")
        replacement = _text(operation["replacement"])
        if replacement and not replacement.endswith("\n"):
            raise CompletionError("range replacement must end with newline")
        replacements.setdefault(name, []).append(
            (sum(map(len, lines[: start - 1])), sum(map(len, lines[:end])), replacement)
        )


def _process_patches(
    patches: list[dict],
    records: dict[str, dict],
    context: CodeContext,
    replacements: dict[str, list[tuple[int, int, str]]],
) -> None:
    for operation in patches:
        record, name, body = _bind_operation(operation, {"id", "file_sha256", "before", "after"}, records, context)
        before, after = _text(operation["before"]), _text(operation["after"])
        excerpt = record.get("patch_excerpt")
        if not record.get("patchable") or not before or before not in excerpt:
            raise CompletionError("patch requires exact canonical excerpt evidence")
        span = record["source"]["lines"]
        lines = body.splitlines(keepends=True)
        offset = sum(map(len, lines[: span["start"] - 1]))
        local = "".join(lines[span["start"] - 1 : span["end"]])
        if local.count(before) != 1:
            raise CompletionError("patch source is absent or ambiguous")
        start = offset + local.index(before)
        replacements.setdefault(name, []).append((start, start + len(before), after))


def _process_json_updates(
    json_updates: list[dict],
    records: dict[str, dict],
    context: CodeContext,
    json_documents: dict[str, object],
    json_pointers: dict[str, list[list[str]]],
) -> None:
    for operation in json_updates:
        record, name, body = _bind_operation(operation, {"id", "file_sha256", "pointer", "value"}, records, context)
        if "json_field" not in record and not record.get("json_additions"):
            raise CompletionError("JSON update requires canonical configuration evidence")
        pointer = operation["pointer"]
        if not isinstance(pointer, list) or not all(isinstance(k, str) for k in pointer):
            raise CompletionError("JSON pointer must be a list of property names")
        previous = json_pointers.setdefault(name, [])
        if any(pointer[: len(p)] == p or p[: len(pointer)] == pointer for p in previous):
            raise CompletionError("JSON updates overlap")
        previous.append(pointer)
        document = json_documents.setdefault(name, json.loads(body))
        if record.get("json_additions"):
            if len(pointer) != 1 or not isinstance(document, dict) or pointer[0] in document:
                raise CompletionError("JSON aggregate permits only absent top-level fields")
            field = pointer[0]
        else:
            field = record["json_field"]["key"]
        _json_update(document, pointer, operation["value"], field)


def _process_creates(
    creates_ops: list[dict],
    root: Path,
    context: CodeContext,
    environ: dict,
    creates: dict[str, bytes],
) -> None:
    for operation in creates_ops:
        if (
            not isinstance(operation, dict)
            or set(operation) != {"path", "content"}
            or not isinstance(operation["path"], str)
        ):
            raise CompletionError("invalid creation operation")
        name = operation["path"]
        if name in creates or name in context.sources:
            raise CompletionError("creation path is duplicated or already tracked")
        _creation_path(root, name, environ)
        creates[name] = _text(operation["content"]).encode()
