"""Versioned, source-bound edits; original files never become model attachments."""

from __future__ import annotations

import ast
import json
import os
import stat
import tempfile
import tomllib
from pathlib import Path

from .code_context import CodeContext, digest, safe_path
from .edit_operations import _creation_path, _json_update, _text
from .edit_schema import MAX_CHANGE_BYTES, SCHEMA, enrich_records, response_format
from .errors import CompletionError

__all__ = [
    "MAX_CHANGE_BYTES",
    "SCHEMA",
    "apply_plan",
    "enrich_records",
    "response_format",
]


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
    root: Path,
    staged: dict[str, bytes],
    creates: dict[str, bytes],
    context: CodeContext,
    environ: dict,
) -> None:
    for name in staged:
        if name in creates:
            _creation_path(root, name, environ)
        elif safe_path(root, name).read_bytes() != context.sources[name]:
            raise CompletionError("edit plan source changed before apply")


def apply_plan(
    root: Path,
    context: CodeContext,
    selected: list[dict],
    answer: dict,
    environ: dict,
    *,
    dry_run: bool = False,
) -> list[dict]:
    _validate_envelope(answer)
    records = {r["id"]: r for r in selected}
    replacements: dict[str, list[tuple[int, int, str]]] = {}
    json_documents: dict[str, object] = {}
    json_pointers: dict[str, list[list[str]]] = {}
    creates: dict[str, bytes] = {}

    _process_edits(answer["edits"], records, context, replacements)
    _process_patches(answer["patches"], records, context, replacements)
    _process_json_updates(answer["json_updates"], records, context, json_documents, json_pointers)
    _process_creates(answer["creates"], root, context, environ, creates)

    staged = _stage_replacements(replacements, context, json_documents)
    staged.update(
        {
            name: (json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
            for name, doc in json_documents.items()
        }
    )
    staged.update(creates)
    _verify_staged_content(staged, creates, context)

    _reobserve(root, staged, creates, context, environ)
    if dry_run:
        return []
    receipts = []
    with tempfile.TemporaryDirectory(prefix="subllm-plan-", dir=root) as temporary:
        pending = {}
        for i, (name, data) in enumerate(staged.items()):
            file = Path(temporary) / str(i)
            file.write_bytes(data)
            file.chmod(0o644 if name in creates else stat.S_IMODE(safe_path(root, name).stat().st_mode))
            pending[name] = file
        _reobserve(root, staged, creates, context, environ)
        for name, file in pending.items():
            target = safe_path(root, name)
            if name in creates:
                target.parent.mkdir(parents=True, exist_ok=True)
                safe_path(root, name)  # Recheck newly created parents before exclusive installation.
                os.link(file, target)  # Atomic no-clobber creation, including a concurrently created target.
            else:
                os.replace(file, target)
            receipts.append(
                {
                    "path": name,
                    "before_sha256": None if name in creates else digest(context.sources[name]),
                    "after_sha256": digest(staged[name]),
                    "operation": "create" if name in creates else "edit",
                }
            )
    return receipts
