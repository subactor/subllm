"""Explicit real-runtime suite: missing pins fail; no conditional test skipping."""

import os
import subprocess

from subllm.code_context import encode, extract_context
from subllm.dsl_edit import editing_records
from subllm.edit_contract import SCHEMA, apply_plan, enrich_records


def test_real_canonical_code2dsl_extracts_python_and_js_without_full_file_context(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    body = "def allow(user):\n    return user is not None\n" + "# PRIVATE_UNRELATED_SENTINEL\n" * 15000
    (tmp_path / "auth.py").write_text(body)
    (tmp_path / "auth.mjs").write_text("export function allow(user) { return user !== null; }\n")
    (tmp_path / ".env.py").write_text('PRIVATE_CREDENTIAL_SENTINEL = "secret"\n')
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    context = extract_context(tmp_path, os.environ)
    assert {r["source"]["path"] for r in context.records} == {"auth.py", "auth.mjs"}
    sent = encode([context.projection(r) for r in context.records])
    assert "PRIVATE_UNRELATED_SENTINEL" not in sent
    assert "PRIVATE_CREDENTIAL_SENTINEL" not in sent
    assert len(sent.encode()) < len(body.encode()) / 10
    assert any(r["source"]["symbol"] == "allow" for r in context.records)
    assert not (tmp_path / ".intent").exists()
    assert not context.warnings


def test_real_extraction_preserves_operator_ignore_policy(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "auth.py").write_text("def allow(user):\n    return True\n")
    (tmp_path / "restricted.py").write_text('def private_credentials():\n    return "DO_NOT_SEND"\n')
    (tmp_path / ".aiderignore").write_text("restricted.py\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    context = extract_context(tmp_path, os.environ)
    assert {r["source"]["path"] for r in context.records} == {"auth.py"}
    assert "DO_NOT_SEND" not in encode([context.projection(r) for r in context.records])


def test_real_docs_configuration_and_large_node_edits(tmp_path):
    import json

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "docs/guide.md").write_text("# Guide\n\nThe `allow` function must reject anonymous users.\n")
    (tmp_path / "config/service.json").write_text('{"enabled": false, "untouched": 42}\n')
    body = "def allow(user):\n    allowed = True\n" + "    # unrelated padding\n" * 200 + "    return allowed\n"
    (tmp_path / "auth.py").write_text(body)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    context = extract_context(tmp_path, os.environ)
    selected = enrich_records(context, editing_records(context, [context.projection(r) for r in context.records]))
    code = next(
        r
        for r in selected
        if r["source"]["path"] == "auth.py" and r["patchable"] and "allowed = True" in r["patch_excerpt"]
    )
    config = next(r for r in selected if r.get("json_field", {}).get("key") == "enabled")
    doc = next(
        r
        for r in selected
        if r["source"]["path"] == "docs/guide.md" and r["patchable"] and "anonymous" in r["patch_excerpt"]
    )
    answer = dict(
        schema=SCHEMA,
        summary="bounded integration",
        edits=[],
        patches=[
            dict(
                id=code["id"],
                file_sha256=code["file_sha256"],
                before="allowed = True",
                after="allowed = user is not None",
            ),
            dict(id=doc["id"], file_sha256=doc["file_sha256"], before="anonymous", after="unauthenticated"),
        ],
        creates=[dict(path="docs/new.md", content="# New guide\n")],
        json_updates=[dict(id=config["id"], file_sha256=config["file_sha256"], pointer=["enabled"], value=True)],
    )
    apply_plan(tmp_path, context, selected, answer, dict(os.environ))
    assert (tmp_path / "auth.py").read_text() == body.replace("allowed = True", "allowed = user is not None")
    assert json.loads((tmp_path / "config/service.json").read_text()) == {"enabled": True, "untouched": 42}
    assert "unauthenticated" in (tmp_path / "docs/guide.md").read_text()
    assert (tmp_path / "docs/new.md").is_file()


def test_repeated_calls_on_one_line_preserve_canonical_identity(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "repeat.mjs").write_text('export const value = () => Math.abs(-1) + Math.abs(-1);\n')
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    context = extract_context(tmp_path, os.environ)
    assert context.records
    assert len({r['id'] for r in context.records}) == len(context.records)
    calls = [r for r in context.records if r['source'].get('rawExcerpt') == 'Math.abs(-1)']
    assert len(calls) == 1
