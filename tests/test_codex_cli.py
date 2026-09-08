from __future__ import annotations

import json
import os
import sys

import pytest

from subllm.codex_cli import invoke
from subllm.errors import CompletionError
from subllm.resolver import available_routes, configured_routes


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    def install(body):
        script = tmp_path / "codex"
        script.write_text(f"#!{sys.executable}\n" + body)
        script.chmod(0o700)
        monkeypatch.setenv("PATH", str(tmp_path))
        return script
    return install


def test_fixed_transport_no_credentials_or_checkout(fake_codex):
    fake_codex('''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
assert args[0] == 'exec'
assert '--ignore-user-config' in args and '--ephemeral' in args
assert args[args.index('--sandbox') + 1] == 'read-only'
assert args[args.index('--model') + 1] == 'gpt-5.6-sol'
assert not any(k.endswith('API_KEY') for k in os.environ)
assert not (Path.cwd() / '.git').exists()
request = json.load(sys.stdin)
assert request['messages'][0]['content'] == 'hello'
Path(args[args.index('--output-last-message') + 1]).write_text('answer')
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':7,'output_tokens':2}}))
''')
    assert invoke("gpt-5.6-sol", [{"role": "user", "content": "hello"}], 2, None) == (
        "answer", {"input_tokens": 7, "output_tokens": 2})


def test_timeout_reaps_descendants(fake_codex, tmp_path):
    marker = tmp_path / "escaped"
    child = f"import time;time.sleep(0.5);open({str(marker)!r},'w').write('bad')"
    fake_codex(f"import subprocess,sys,time\nsubprocess.Popen([sys.executable,'-c',{child!r}])\ntime.sleep(5)\n")
    with pytest.raises(CompletionError) as exc:
        invoke("gpt-5.6-sol", [{"role": "user", "content": "hello"}], 0.2, None)
    assert exc.value.diagnostic_code == "SUBLLM-CODEX-TIMEOUT"
    import time
    time.sleep(0.6)
    assert not marker.exists()


@pytest.mark.parametrize("event", [{"type": "turn.failed"}, {"type": "error"}, {"type": "item.completed"}])
def test_incomplete_output_fails_closed(fake_codex, event):
    fake_codex(f'''import sys
from pathlib import Path
Path(sys.argv[sys.argv.index('--output-last-message')+1]).write_text('untrusted')
print({json.dumps(event)!r})
''')
    with pytest.raises(CompletionError, match="incomplete or invalid"):
        invoke("gpt-5.6-sol", [{"role": "user", "content": "hello"}], 2, None)


def test_exit_error_does_not_echo_output(fake_codex):
    fake_codex("import sys\nprint('secret-like-error',file=sys.stderr)\nsys.exit(1)\n")
    with pytest.raises(CompletionError) as exc:
        invoke("gpt-5.6-sol", [{"role": "user", "content": "hello"}], 2, None)
    assert "secret-like-error" not in str(exc.value)


def test_route_is_explicit_and_preserves_api_provider(fake_codex, monkeypatch):
    fake_codex("pass\n")
    monkeypatch.delenv("SUBLLM_PROVIDER_ORDER", raising=False)
    routes = available_routes("organism-guard", "refactor", environ={"PATH": os.environ["PATH"]})
    assert len(routes) == 1
    assert routes[0].provider == routes[0].transport == "codex-cli"
    assert routes[0].api_key == routes[0].api_base == ""
    with pytest.raises(ValueError, match="local Codex login"):
        routes[0].litellm_kwargs()
    assert all(r.provider != "codex-cli" for r in configured_routes("onedev-agent", "code-edit"))


def test_missing_binary_has_no_available_route(monkeypatch, tmp_path):
    monkeypatch.delenv("SUBLLM_PROVIDER_ORDER", raising=False)
    assert not available_routes("organism-guard", "refactor", environ={"PATH": str(tmp_path)})
