"""Cline CLI transport uses local login/subscription without extra credentials."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from subllm.cline_cli import MAX_PROMPT_BYTES, invoke
from subllm.errors import CompletionError

MESSAGES = [{"role": "user", "content": "hello"}]


@pytest.fixture
def fake_cline(tmp_path, monkeypatch):
    def install(body):
        executable = tmp_path / "cline"
        executable.write_text(f"#!{sys.executable}\n" + body)
        executable.chmod(0o700)
        monkeypatch.setenv("PATH", str(tmp_path))
    return install


def test_cline_cli_invocation_and_usage(fake_cline, monkeypatch, tmp_path):
    marker = tmp_path / "root-path"
    monkeypatch.setenv("SOME_API_KEY", "secret-key")
    fake_cline('''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
assert args[:4] == ["--json", "-p", "-m", "cline-pass/deepseek-v4.1-flash-1017"]
assert args[4] == "[user]\\nhello" and len(args) == 5
assert not any(k.endswith("API_KEY") or k.endswith("TOKEN") for k in os.environ)
root = Path.cwd()
assert root.stat().st_mode & 0o777 == 0o700
''' + f'Path({str(marker)!r}).write_text(str(root))\n' + '''
print(json.dumps({"type":"agent_event","event":{"type":"content_start","text":"pong"}}))
print(json.dumps({"type":"agent_event","event":{"type":"usage","inputTokens":12,"outputTokens":4,"cacheReadTokens":2,"cost":0}}))
''')
    res, usage = invoke("cline-pass/deepseek-v4.1-flash-1017", MESSAGES, 5, None)
    assert res == "pong"
    assert usage == {"input_tokens": 12, "output_tokens": 4, "cached_input_tokens": 2}
    assert not Path(marker.read_text()).exists()


@pytest.mark.parametrize("content", ['{"ok":true}', '```json\n{"ok":true}\n```'])
def test_json_object_normalization(fake_cline, content):
    fake_cline(f'''import json
print(json.dumps({{"type":"agent_event","event":{{"type":"content_start","text":{content!r}}}}}))
print(json.dumps({{"type":"agent_event","event":{{"type":"usage","inputTokens":5,"outputTokens":5}}}}))
''')
    assert json.loads(invoke("cline-pass/deepseek-v4.1-flash-1017", MESSAGES, 5, {"type": "json_object"})[0]) == {"ok": True}


@pytest.mark.parametrize("content", ["", "   ", "not-json"])
def test_reject_invalid_or_empty_output(fake_cline, content):
    fake_cline(f'''import json
print(json.dumps({{"type":"agent_event","event":{{"type":"content_start","text":{content!r}}}}}))
print(json.dumps({{"type":"agent_event","event":{{"type":"usage","inputTokens":1,"outputTokens":1}}}}))
''')
    if not content.strip():
        with pytest.raises(CompletionError):
            invoke("cline-pass/deepseek-v4.1-flash-1017", MESSAGES, 5, None)
    else:
        with pytest.raises(CompletionError):
            invoke("cline-pass/deepseek-v4.1-flash-1017", MESSAGES, 5, {"type": "json_object"})


def test_bounds_and_unsupported_requests(fake_cline):
    fake_cline('raise AssertionError("must not start")')
    cases = [
        ("cline-pass/deepseek-v4.1-flash-1017", [{"role": "user", "content": "x" * (MAX_PROMPT_BYTES + 1)}], 5, None),
        ("cline-pass/deepseek-v4.1-flash-1017", [{"role": "user", "content": "\x00"}], 5, None),
        ("cline-pass/deepseek-v4.1-flash-1017", MESSAGES, float("inf"), None),
        ("cline-pass/deepseek-v4.1-flash-1017", MESSAGES, 0, None),
        ("cline-pass/deepseek-v4.1-flash-1017", MESSAGES, -1, None),
        ("cline-pass/deepseek-v4.1-flash-1017", MESSAGES, 5, {"type": "json_schema", "json_schema": {"schema": {}}}),
    ]
    for args in cases:
        with pytest.raises(CompletionError):
            invoke(*args)


def test_missing_cli(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(CompletionError) as exc:
        invoke("cline-pass/deepseek-v4.1-flash-1017", MESSAGES, 5, None)
    assert exc.value.diagnostic_code == "SUBLLM-CLINE-CLI-UNAVAILABLE"
