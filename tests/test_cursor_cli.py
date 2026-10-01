"""Cursor CLI uses local login without changing default reviewer policy."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from subllm import complete, configured_routes
from subllm.cursor_cli import MAX_PROMPT_BYTES, invoke
from subllm.errors import CompletionError
from subllm.policy_config import load_policy_config

MESSAGES = [{"role": "user", "content": "hello"}]


@pytest.fixture
def fake_cursor(tmp_path, monkeypatch):
    def install(body):
        executable = tmp_path / "cursor-agent"
        executable.write_text(f"#!{sys.executable}\n" + body)
        executable.chmod(0o700)
        monkeypatch.setenv("PATH", str(tmp_path))
    return install


def test_local_login_private_workspace_and_tool_denials(fake_cursor, monkeypatch, tmp_path):
    marker = tmp_path / "workspace-path"
    monkeypatch.setenv("CURSOR_API_KEY", "test-do-not-forward")
    fake_cursor('''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
assert args[:7] == ["--print", "--trust", "--mode", "ask", "--model", "auto", "--output-format"]
assert args[7] == "json" and args[8] == "--workspace"
assert args[10] == "[user]\\nhello" and len(args) == 11
assert not any(k.endswith("API_KEY") or k.endswith("TOKEN") for k in os.environ)
root = Path(args[9])
assert root == Path.cwd() and root.stat().st_mode & 0o777 == 0o700
config = root / ".cursor/cli.json"
permissions = json.loads(config.read_text())["permissions"]
assert permissions["allow"] == []
assert set(permissions["deny"]) == {
"Shell(*)", "Read(**)", "Read(/**)", "Write(**)", "Write(/**)", "WebFetch(*)", "Mcp(*:*)"}
''' + f'Path({str(marker)!r}).write_text(str(root))\n' + '''
print(json.dumps({"type":"result", "subtype":"success", "is_error":False,
"result":" answer ", "usage":{"input_tokens":2,"output_tokens":3,"cache_read_input_tokens":1}}))
''')
    assert invoke("auto", MESSAGES, 5, None) == ("answer", {
        "input_tokens": 2, "output_tokens": 3, "cached_input_tokens": 1})
    assert not Path(marker.read_text()).exists()


@pytest.mark.parametrize("content", ['{"ok":true}', '```json\n{"ok":true}\n```'])
def test_json_object_normalization(fake_cursor, content):
    envelope = {"type": "result", "subtype": "success", "is_error": False, "result": content}
    fake_cursor(f"print({json.dumps(envelope)!r})")
    assert json.loads(invoke("auto", MESSAGES, 5, {"type": "json_object"})[0]) == {"ok": True}


@pytest.mark.parametrize("envelope", [
    [], {"type": "result", "subtype": "error", "is_error": True, "result": "test-private-detail"},
    {"type": "result", "subtype": "success", "result": "answer"},
    {"type": "result", "subtype": "success", "is_error": False, "result": ""},
])
def test_reject_incomplete_and_error_envelopes(fake_cursor, envelope):
    fake_cursor(f"print({json.dumps(envelope)!r})")
    with pytest.raises(CompletionError) as exc:
        invoke("auto", MESSAGES, 5, None)
    assert "test-private-detail" not in str(exc.value)


@pytest.mark.parametrize("content", ["[]", "plain text", '```json\n{}\n```\nextra'])
def test_reject_non_object_response(fake_cursor, content):
    fake_cursor(f"print({json.dumps({'type':'result','subtype':'success','is_error':False,'result':content})!r})")
    with pytest.raises(CompletionError):
        invoke("auto", MESSAGES, 5, {"type": "json_object"})


def test_bounds_and_unsupported_requests(fake_cursor):
    fake_cursor('raise AssertionError("must not start")')
    cases = [
        ("auto", [{"role": "user", "content": "x" * MAX_PROMPT_BYTES}], 5, None),
        ("auto", [{"role": "user", "content": "\x00"}], 5, None),
        ("named-paid-model", MESSAGES, 5, None),
        ("auto", MESSAGES, float("inf"), None),
        ("auto", MESSAGES, 0, None),
        ("auto", MESSAGES, 5, {"type":"json_schema", "json_schema":{"schema":{}}}),
    ]
    for args in cases:
        with pytest.raises(CompletionError) as exc:
            invoke(*args)
        assert exc.value.diagnostic_code != "SUBLLM-CURSOR-CLI-FAILED"


def test_missing_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(CompletionError) as exc:
        invoke("auto", MESSAGES, 5, None)
    assert exc.value.diagnostic_code == "SUBLLM-CURSOR-CLI-UNAVAILABLE"


@pytest.mark.parametrize(("body", "code"), [
    ('import time; time.sleep(30)', "TIMEOUT"),
    ('print("x" * 1_100_000)', "BUDGET"),
    ('import sys; sys.exit(1)', "FAILED"),
    ('print("invalid json")', "OUTPUT"),
])
def test_runner_failures(fake_cursor, body, code):
    fake_cursor(body)
    with pytest.raises(CompletionError) as exc:
        invoke("auto", MESSAGES, 0.5 if code == "TIMEOUT" else 5, None)
    assert exc.value.diagnostic_code == f"SUBLLM-CURSOR-CLI-{code}"


def test_policy_opt_in_and_complete_dispatch(fake_cursor, monkeypatch, tmp_path):
    policy = Path(__file__).resolve().parents[1] / "subllm.toml"
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy))
    assert load_policy_config().providers["cursor-cli"].enabled is False
    assert all(route.provider != "cursor-cli" for route in configured_routes("validator-agent", "direct-pr-review"))
    enabled = tmp_path / "policy.toml"
    enabled.write_text(policy.read_text() +
                       '\n[providers.cursor-cli]\nenabled = true\npriority = 21\ndefault_model = "cursor-auto"\n')
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(enabled))
    fake_cursor('print(\'{"type":"result","subtype":"success","is_error":false,"result":"ok"}\')')
    response = complete("validator-agent", "direct-pr-review", MESSAGES, timeout_seconds=5,
                        environ={"SUBLLM_PROVIDER_ORDER": "cursor-cli"})
    assert response.content == "ok"
    assert response.provider == "cursor-cli" and response.model == "auto"
