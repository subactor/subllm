"""Versioned, source-bound edits; original files never become model attachments."""

from __future__ import annotations

import json
import os
import stat
import tempfile
from pathlib import Path

from .code_context import CodeContext, digest, safe_path
from .edit_plan import (
    _process_creates,
    _process_edits,
    _process_json_updates,
    _process_patches,
    _validate_envelope,
)
from .edit_schema import MAX_CHANGE_BYTES, SCHEMA, enrich_records, response_format
from .edit_staging import _reobserve, _stage_replacements, _verify_staged_content

__all__ = [
    "MAX_CHANGE_BYTES",
    "SCHEMA",
    "apply_plan",
    "enrich_records",
    "response_format",
]


def apply_plan(
    root: Path, context: CodeContext, selected: list[dict], answer: dict, environ: dict, *, dry_run: bool = False
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
