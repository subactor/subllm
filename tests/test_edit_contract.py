import json
import subprocess
from types import SimpleNamespace

import pytest
from test_code_context import context_record

from subllm.code_context import CodeContext, digest
from subllm.dsl_edit import editing_records, execute_dsl_edit
from subllm.edit_contract import SCHEMA, apply_plan, enrich_records
from subllm.errors import CompletionError


def plan(**operations):
    return dict(schema=SCHEMA, summary="bounded change", edits=[], patches=[], creates=[], json_updates=[]) | operations


def fixture(root, body, name="src/auth.py", record=None):
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    file = root / name
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(body)
    record = record or context_record(name=name, body=body)
    context = CodeContext([record], {name: body.encode()}, {})
    selected = enrich_records(context, editing_records(context, [context.projection(record)]))
    return context, selected, file


def test_patch_large_node_preserves_unseen_suffix(tmp_path):
    body = "def allow(user):\n    result = True\n" + "    # unrelated\n" * 300 + "    return result\n"
    record = context_record(body=body)
    record["source"]["rawExcerpt"] = body[:2000]
    context, selected, file = fixture(tmp_path, body, record=record)
    assert not selected[0]["editable"] and selected[0]["patchable"]
    answer = plan(
        patches=[
            dict(
                id="auth", file_sha256=digest(body.encode()), before="result = True", after="result = user is not None"
            )
        ]
    )
    apply_plan(tmp_path, context, selected, answer, {})
    assert file.read_text() == body.replace("result = True", "result = user is not None")


def test_patch_cannot_target_unseen_text_or_ambiguous_occurrence(tmp_path):
    body = "def allow(user):\n    value = True\n    return value\n"
    context, selected, file = fixture(tmp_path, body)
    for before in ["invented", "value"]:
        with pytest.raises(CompletionError, match="evidence|ambiguous"):
            apply_plan(
                tmp_path,
                context,
                selected,
                plan(patches=[dict(id="auth", file_sha256=digest(body.encode()), before=before, after="x")]),
                {},
            )
        assert file.read_text() == body


def test_json_updates_stay_under_canonical_field_and_preserve_other_values(tmp_path):
    body = '{"service": {"enabled": false}, "untouched": [1, 2]}\n'
    record = context_record(name="config/service.json", body=body)
    record["source"].update(symbol="service", rawExcerpt="Configure service")
    record["statement"]["kind"] = "configuration_declaration"
    record["metadata"] = {"format": "json"}
    context, selected, file = fixture(tmp_path, body, "config/service.json", record)
    operation = dict(id="auth", file_sha256=digest(body.encode()), pointer=["service", "enabled"], value=True)
    with pytest.raises(CompletionError, match="outside"):
        apply_plan(tmp_path, context, selected, plan(json_updates=[operation | {"pointer": ["untouched"]}]), {})
    apply_plan(tmp_path, context, selected, plan(json_updates=[operation]), {})
    assert json.loads(file.read_text()) == {"service": {"enabled": True}, "untouched": [1, 2]}


def test_new_file_ignores_existing_targets_and_invalid_batch_are_rejected_before_write(tmp_path):
    context, selected, file = fixture(tmp_path, "def allow(user):\n    return True\n")
    (tmp_path / ".aiderignore").write_text("private/**\n")
    for path in ["src/auth.py", ".env.json", "../escape.py", "private/secret.py"]:
        with pytest.raises(CompletionError):
            apply_plan(tmp_path, context, selected, plan(creates=[dict(path=path, content="x = 1\n")]), {})
    with pytest.raises(CompletionError, match="syntax"):
        apply_plan(
            tmp_path,
            context,
            selected,
            plan(creates=[dict(path="docs/new.md", content="# New\n"), dict(path="src/bad.py", content="def !")]),
            {},
        )
    assert not (tmp_path / "docs/new.md").exists()
    answer = plan(creates=[dict(path="docs/new.md", content="# New\n"), dict(path="src/new.py", content="VALUE = 3\n")])
    receipts = apply_plan(tmp_path, context, selected, answer, {})
    assert (tmp_path / "docs/new.md").read_text() == "# New\n"
    assert all(r["operation"] == "create" and r["before_sha256"] is None for r in receipts)
    assert file.read_text() == "def allow(user):\n    return True\n"


@pytest.mark.parametrize("invalid", ["```json\n{}\n```", '{"ids":[],"ids":[]}', '{"bad":NaN}'])
def test_invalid_json_is_repaired_once_without_replaying_untrusted_response(tmp_path, monkeypatch, invalid):
    context, _, file = fixture(tmp_path, "def allow(user):\n    return True\n")
    monkeypatch.setattr("subllm.dsl_edit.extract_context", lambda *args: context)
    responses = [
        invalid,
        '{"ids":["auth"]}',
        json.dumps(
            plan(
                patches=[
                    dict(
                        id="auth",
                        file_sha256=digest(context.sources["src/auth.py"]),
                        before="return True",
                        after="return user is not None",
                    )
                ]
            )
        ),
    ]
    calls = []

    def complete(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(content=responses.pop(0), provider="zai", model="glm-5.3")

    _, _, receipt = execute_dsl_edit(tmp_path, "fix", provider=None, environ={}, timeout_seconds=30, complete=complete)
    assert len(calls) == 3
    assert "Previous response was invalid JSON" in calls[1][0][2][0]["content"]
    assert invalid not in calls[1][0][2][1]["content"]
    assert "user is not None" in file.read_text()
    assert json.loads(receipt)["queries"][0]["validation_error"] == "invalid_json_object"


def test_repeated_invalid_json_is_bounded_and_never_applies(tmp_path, monkeypatch):
    context, _, file = fixture(tmp_path, "def allow(user):\n    return True\n")
    monkeypatch.setattr("subllm.dsl_edit.extract_context", lambda *args: context)
    calls = []

    def complete(*args, **kwargs):
        calls.append(1)
        return SimpleNamespace(content="not json", provider="zai", model="glm-5.3")

    with pytest.raises(CompletionError, match="2 bounded attempts"):
        execute_dsl_edit(tmp_path, "fix", provider=None, environ={}, timeout_seconds=30, complete=complete)
    assert len(calls) == 2 and file.read_bytes() == context.sources["src/auth.py"]


def test_invalid_plan_is_repaired_before_any_creation(tmp_path, monkeypatch):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    context = CodeContext([], {}, {})
    monkeypatch.setattr("subllm.dsl_edit.extract_context", lambda *args: context)
    responses = [
        plan(creates=[dict(path="docs/new.md", content="# New\n"), dict(path="bad.py", content="def !")]),
        plan(creates=[dict(path="docs/new.md", content="# New\n")]),
    ]
    calls = []

    def complete(*args, **kwargs):
        assert not (tmp_path / "docs/new.md").exists()
        calls.append((args, kwargs))
        return SimpleNamespace(content=json.dumps(responses.pop(0)), provider="openrouter", model="z-ai/glm-5.3")

    execute_dsl_edit(tmp_path, "create guide", provider=None, environ={}, timeout_seconds=30, complete=complete)
    assert len(calls) == 2 and (tmp_path / "docs/new.md").is_file()
    assert calls[0][1]["response_format"]["type"] == "json_schema"
    assert "invalid document syntax" in calls[1][0][2][0]["content"]
    assert "SUBLLM_PROVIDER_ORDER" not in calls[0][1]["environ"]


def test_selection_repair_uses_exact_page_ids(tmp_path):
    from subllm.code_context import select_code_context

    context, _, _ = fixture(tmp_path, "def allow(user):\n    return True\n")
    responses = [{"ids": ["invented"]}, {"ids": ["auth"]}]
    calls = []

    def query(function, instruction, payload):
        calls.append(instruction)
        return responses.pop(0)

    assert select_code_context(context, "fix", query)[0]["id"] == "auth"
    assert len(calls) == 2 and "unknown IDs" in calls[1]


def test_json_aggregate_can_add_only_absent_root_fields(tmp_path):
    body = '{"allowedPaths": ["src/auth.py"]}\n'
    record = context_record(name="config/intent.json", body=body)
    record["statement"]["kind"] = "configuration_file_fact"
    record["metadata"] = {"format": "json"}
    context, selected, file = fixture(tmp_path, body, "config/intent.json", record)
    assert selected[0]["json_additions"]
    op = dict(id="auth", file_sha256=digest(body.encode()), pointer=["delivery"], value={"acceptedBaseSha": "a" * 40})
    for pointer in [["allowedPaths"], ["delivery", "acceptedBaseSha"]]:
        with pytest.raises(CompletionError, match="absent top-level"):
            apply_plan(tmp_path, context, selected, plan(json_updates=[op | {"pointer": pointer}]), {})
    apply_plan(tmp_path, context, selected, plan(json_updates=[op]), {})
    assert json.loads(file.read_text()) == {"allowedPaths": ["src/auth.py"], "delivery": {"acceptedBaseSha": "a" * 40}}
