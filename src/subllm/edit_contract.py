"""Versioned, source-bound edits; original files never become model attachments."""

from __future__ import annotations

import ast
import json
import os
import stat
import subprocess
import tempfile
import tomllib
from pathlib import Path

from .code_context import CodeContext, digest, encode, safe_path
from .errors import CompletionError

SCHEMA = "subllm.edit-plan/v2"
MAX_CHANGE_BYTES = 262_144


def response_format(function: str, records: list[dict]) -> dict:
    """Make the wire response contract explicit, not merely a prose suggestion."""

    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    def array(items):
        return {"type": "array", "items": items}

    string = {"type": "string"}
    identity = {"type": "string", "enum": [r["id"] for r in records]} if records else string
    if function == "code-context":
        schema = obj({"ids": array(identity)})
    else:
        bound = {"id": identity, "file_sha256": string}
        schema = obj(
            {
                "schema": {"type": "string", "enum": [SCHEMA]},
                "summary": string,
                "edits": array(obj({**bound, "replacement": string})),
                "patches": array(obj({**bound, "before": string, "after": string})),
                "creates": array(obj({"path": string, "content": string})),
                "json_updates": array(obj({**bound, "pointer": array(string), "value": {}})),
            }
        )
    return {
        "type": "json_schema",
        "json_schema": {"name": function.replace("-", "_"), "strict": True, "schema": schema},
    }


def enrich_records(context: CodeContext, records: list[dict]) -> list[dict]:
    """Expose only canonical excerpts and bounded configuration value evidence."""
    originals = {r["id"]: r for r in context.records}
    result = []
    for record in records:
        original = originals[record["id"]]
        source = original["source"]
        excerpt = source.get("rawExcerpt")
        span = source["lines"]
        actual = "\n".join(context.sources[source["path"]].decode().splitlines()[span["start"] - 1 : span["end"]])
        patchable = (
            isinstance(excerpt, str)
            and bool(excerpt.strip())
            and len(excerpt) <= 2000
            and bool(actual)
            and original["statement"]["kind"] not in {"module_fact", "configuration_file_fact"}
        )
        extra = {"patchable": patchable, "patch_excerpt": excerpt if patchable else None}
        if (
            source["path"].endswith(".json")
            and original["statement"]["kind"] == "configuration_declaration"
            and original.get("metadata", {}).get("format") == "json"
        ):
            value = json.loads(context.sources[source["path"]])
            key = source.get("symbol")
            if isinstance(value, dict) and key in value:
                field = value[key]
                extra["json_field"] = {
                    "key": key,
                    "value": field if len(encode(field).encode()) <= 2000 else None,
                    "value_omitted": len(encode(field).encode()) > 2000,
                }
        if (source['path'].endswith('.json')
                and original['statement']['kind'] == 'configuration_file_fact'
                and original.get('metadata', {}).get('format') == 'json'
                and isinstance(json.loads(context.sources[source['path']]), dict)):
            extra['json_additions'] = True
        result.append({**record, **extra})
    return result


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


def apply_plan(
    root: Path, context: CodeContext, selected: list[dict], answer: dict, environ: dict, *, dry_run: bool = False
) -> list[dict]:
    required = {"schema", "summary", "edits", "patches", "creates", "json_updates"}
    if set(answer) != required or answer["schema"] != SCHEMA or not isinstance(answer["summary"], str):
        raise CompletionError("invalid edit plan v2 envelope")
    groups = [answer[k] for k in ("edits", "patches", "creates", "json_updates")]
    if any(not isinstance(g, list) for g in groups) or not 1 <= sum(map(len, groups)) <= 32:
        raise CompletionError("edit plan requires 1 to 32 operations")
    records = {r["id"]: r for r in selected}
    replacements: dict[str, list[tuple[int, int, str]]] = {}
    json_documents: dict[str, object] = {}
    json_pointers: dict[str, list[list[str]]] = {}
    creates: dict[str, bytes] = {}

    def bound(operation: dict, keys: set[str]) -> tuple[dict, str, str]:
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

    for operation in answer["edits"]:
        record, name, body = bound(operation, {"id", "file_sha256", "replacement"})
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
    for operation in answer["patches"]:
        record, name, body = bound(operation, {"id", "file_sha256", "before", "after"})
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
    for operation in answer["json_updates"]:
        record, name, body = bound(operation, {"id", "file_sha256", "pointer", "value"})
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
        if record.get('json_additions'):
            if len(pointer) != 1 or not isinstance(document, dict) or pointer[0] in document:
                raise CompletionError('JSON aggregate permits only absent top-level fields')
            field = pointer[0]
        else:
            field = record['json_field']['key']
        _json_update(document, pointer, operation['value'], field)
    for operation in answer["creates"]:
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
    staged: dict[str, bytes] = {}
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
    staged.update(
        {
            name: (json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
            for name, doc in json_documents.items()
        }
    )
    staged.update(creates)
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

    def reobserve() -> None:
        for name in staged:
            if name in creates:
                _creation_path(root, name, environ)
            elif safe_path(root, name).read_bytes() != context.sources[name]:
                raise CompletionError("edit plan source changed before apply")

    reobserve()
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
        reobserve()
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
