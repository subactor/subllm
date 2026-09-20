"""Claude Code and Antigravity CLI transports: fixed argv, no credentials, bounded, opt-in."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from subllm import complete, configured_routes
from subllm.agy_cli import MAX_PROMPT_BYTES
from subllm.agy_cli import invoke as agy_invoke
from subllm.claude_cli import invoke as claude_invoke
from subllm.errors import CompletionError
from subllm.policy import MODELS
from subllm.resolver import available_routes

MESSAGES = [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hello"}]


@pytest.fixture
def fake_cli(tmp_path, monkeypatch):
    """Install a fake local executable first on PATH; the body is Python source."""
    def install(name: str, body: str) -> Path:
        script = tmp_path / name
        script.write_text(f"#!{sys.executable}\n" + body)
        script.chmod(0o700)
        monkeypatch.setenv("PATH", str(tmp_path))
        return script
    return install


CLAUDE_OK = '''import json, os, sys
assert not any(k.endswith("API_KEY") or k.endswith("TOKEN") for k in os.environ), sorted(os.environ)
args = sys.argv[1:]
assert args[0] == "-p" and args[args.index("--output-format") + 1] == "json"
assert args[args.index("--model") + 1] == "claude-sonnet-5"
assert "--no-session-persistence" in args and args[args.index("--tools") + 1] == ""
assert "--disable-slash-commands" in args and args[args.index("--setting-sources") + 1] == ""
assert "--dangerously-skip-permissions" not in args and "--allowedTools" not in args
prompt = sys.stdin.read()
assert prompt == "[system]\\nbe brief\\n\\n[user]\\nhello"
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": " answer ",
  "usage": {"input_tokens": 2, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 5,
            "output_tokens": 4}}))
'''


def test_claude_fixed_transport_and_usage(fake_cli):
    fake_cli("claude", CLAUDE_OK)
    content, usage = claude_invoke("claude-sonnet-5", MESSAGES, 5, None)
    assert content == "answer"
    assert usage == {"input_tokens": 17, "output_tokens": 4, "cached_input_tokens": 5}


def test_claude_json_schema_and_json_object(fake_cli):
    fake_cli("claude", '''import json, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
schema = json.loads(args[args.index("--json-schema") + 1]) if "--json-schema" in args else None
print(json.dumps({"type": "result", "subtype": "success", "is_error": False,
  "result": "", "structured_output": {"ok": True} if schema else None} if schema else
  {"type": "result", "subtype": "success", "is_error": False,
   "result": json.dumps({"json_object_instruction": "single valid JSON object" in prompt})}))
''')
    fmt = {"type": "json_schema", "json_schema": {"schema": {"type": "object"}}}
    assert json.loads(claude_invoke("claude-sonnet-5", MESSAGES, 5, fmt)[0]) == {"ok": True}
    assert json.loads(claude_invoke("claude-sonnet-5", MESSAGES, 5, {"type": "json_object"})[0]) == {
        "json_object_instruction": True}
    with pytest.raises(CompletionError, match="supports text"):
        claude_invoke("claude-sonnet-5", MESSAGES, 5, {"type": "regex"})


@pytest.mark.parametrize(("envelope", "code"), [
    ({"type": "result", "subtype": "success", "is_error": True, "api_error_status": 429}, "SUBLLM-CLAUDE-HTTP-429"),
    ({"type": "result", "subtype": "error_max_turns", "is_error": False}, "SUBLLM-CLAUDE-FAILED"),
    ({"type": "result", "subtype": "success", "is_error": False, "result": "  "}, "SUBLLM-CLAUDE-OUTPUT"),
    ({"type": "system"}, "SUBLLM-CLAUDE-OUTPUT"),
])
def test_claude_error_and_invalid_output_fail_closed(fake_cli, envelope, code):
    fake_cli("claude", f"import json\nprint(json.dumps({envelope!r}))\n")
    with pytest.raises(CompletionError) as exc:
        claude_invoke("claude-sonnet-5", MESSAGES, 5, None)
    assert exc.value.diagnostic_code == code


def test_claude_exit_error_does_not_echo_stderr_or_stdout(fake_cli):
    fake_cli("claude", "import sys\nprint('stdout-secret')\nprint('stderr-secret', file=sys.stderr)\nsys.exit(1)\n")
    with pytest.raises(CompletionError) as exc:
        claude_invoke("claude-sonnet-5", MESSAGES, 5, None)
    assert exc.value.diagnostic_code == "SUBLLM-CLAUDE-FAILED"
    assert "secret" not in str(exc.value)


def test_timeout_reaps_descendants(fake_cli, tmp_path):
    marker = tmp_path / "escaped"
    child = f"import time;time.sleep(0.5);open({str(marker)!r},'w').write('bad')"
    fake_cli("claude", "import subprocess,sys,time\n"
                       f"subprocess.Popen([sys.executable,'-c',{child!r}])\ntime.sleep(5)\n")
    with pytest.raises(CompletionError) as exc:
        claude_invoke("claude-sonnet-5", MESSAGES, 0.2, None)
    assert exc.value.diagnostic_code == "SUBLLM-CLAUDE-TIMEOUT"
    time.sleep(0.7)
    assert not marker.exists()


def test_output_budget_is_enforced(fake_cli):
    fake_cli("claude", "import sys\nsys.stdout.write('x' * 1_200_000)\nsys.stdout.flush()\n")
    with pytest.raises(CompletionError) as exc:
        claude_invoke("claude-sonnet-5", MESSAGES, 5, None)
    assert exc.value.diagnostic_code == "SUBLLM-CLAUDE-BUDGET"


def test_missing_binary_is_reported(monkeypatch, tmp_path):
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(CompletionError) as exc:
        claude_invoke("claude-sonnet-5", MESSAGES, 5, None)
    assert exc.value.diagnostic_code == "SUBLLM-CLAUDE-UNAVAILABLE"
    with pytest.raises(CompletionError) as exc:
        agy_invoke("claude-sonnet-4-6", MESSAGES, 5, None)
    assert exc.value.diagnostic_code == "SUBLLM-AGY-UNAVAILABLE"


AGY_OK = '''import json, os, sys
assert not any(k.endswith("API_KEY") or k.endswith("TOKEN") for k in os.environ), sorted(os.environ)
args = sys.argv[1:]
assert args[args.index("--output-format") + 1] == "json"
assert args[args.index("--model") + 1] == "claude-sonnet-4-6"
assert "--sandbox" in args and "--dangerously-skip-permissions" not in args
prints = [a for a in args if a.startswith("--print=")]
assert len(prints) == 1 and prints[0] == "--print=[system]\\nbe brief\\n\\n[user]\\nhello", prints
print(json.dumps({"conversation_id": "c", "status": "SUCCESS", "response": " answer\\n",
  "usage": {"input_tokens": 9, "output_tokens": 3, "cache_read_tokens": 2}}))
'''


def test_agy_fixed_transport_and_usage(fake_cli):
    fake_cli("agy", AGY_OK)
    content, usage = agy_invoke("claude-sonnet-4-6", MESSAGES, 5, None)
    assert content == "answer"
    assert usage == {"input_tokens": 9, "output_tokens": 3, "cached_input_tokens": 2}


def test_agy_schema_is_passed_as_a_file(fake_cli):
    fake_cli("agy", '''import json, sys
from pathlib import Path
args = sys.argv[1:]
schema = json.loads(Path(args[args.index("--json-schema") + 1]).read_text())
print(json.dumps({"status": "SUCCESS", "response": json.dumps({"type": schema["type"]})}))
''')
    fmt = {"type": "json_schema", "json_schema": {"schema": {"type": "object"}}}
    assert json.loads(agy_invoke("gemini-3.1-pro-high", MESSAGES, 5, fmt)[0]) == {"type": "object"}


@pytest.mark.parametrize(("envelope", "code"), [
    ({"status": "ERROR", "response": "x"}, "SUBLLM-AGY-FAILED"),
    ({"status": "SUCCESS", "response": ""}, "SUBLLM-AGY-OUTPUT"),
    ({"status": "SUCCESS"}, "SUBLLM-AGY-OUTPUT"),
])
def test_agy_error_and_invalid_output_fail_closed(fake_cli, envelope, code):
    fake_cli("agy", f"import json\nprint(json.dumps({envelope!r}))\n")
    with pytest.raises(CompletionError) as exc:
        agy_invoke("claude-sonnet-4-6", MESSAGES, 5, None)
    assert exc.value.diagnostic_code == code


def test_agy_prompt_budget_is_checked_before_execution(fake_cli, tmp_path):
    ran = tmp_path / "ran"
    fake_cli("agy", f"open({str(ran)!r}, 'w').write('x')\n")
    big = [{"role": "user", "content": "x" * (MAX_PROMPT_BYTES + 1)}]
    with pytest.raises(CompletionError) as exc:
        agy_invoke("claude-sonnet-4-6", big, 5, None)
    assert exc.value.diagnostic_code == "SUBLLM-AGY-BUDGET"
    with pytest.raises(CompletionError) as exc:
        agy_invoke("claude-sonnet-4-6", [{"role": "user", "content": "a\x00b"}], 5, None)
    assert exc.value.diagnostic_code == "SUBLLM-AGY-BUDGET"
    assert not ran.exists()


@pytest.mark.parametrize("invoke", [claude_invoke, agy_invoke])
def test_non_text_content_is_rejected_not_dropped(fake_cli, invoke):
    fake_cli("claude", "pass\n")
    fake_cli("agy", "pass\n")
    image = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x"}}]}]
    with pytest.raises(CompletionError) as exc:
        invoke("m", image, 5, None)
    assert exc.value.diagnostic_code == "SUBLLM-CLI-UNSUPPORTED-CONTENT"


# --- catalog, opt-in policy and dispatch ------------------------------------------------------

def test_catalog_maps_sonnet_gemini_and_luna_to_local_logins():
    assert MODELS["claude-sonnet-5"].providers["claude-cli"].wire_model == "claude-sonnet-5"
    assert MODELS["claude-sonnet-4-6"].providers["agy-cli"].wire_model == "claude-sonnet-4-6"
    assert MODELS["gemini-3.1-pro-high"].providers["agy-cli"].wire_model == "gemini-3.1-pro-high"
    assert MODELS["gpt-5.6-luna"].providers["codex-cli"].wire_model == "gpt-5.6-luna"
    assert all(spec.litellm_model == "" for spec in (
        MODELS["claude-sonnet-5"].providers["claude-cli"], MODELS["gpt-5.6-luna"].providers["codex-cli"]))


def _enable(tmp_path: Path, monkeypatch, *providers: str) -> None:
    """Operator opt-in: the repository policy plus explicit rows for the chosen executors."""
    repository = Path(__file__).resolve().parents[1] / "subllm.toml"
    rows = "".join(
        f'\n[providers.{name}]\nenabled = true\npriority = {priority}\ndefault_model = "{model}"\n'
        for name, priority, model in (
            ("agy-cli", 12, "claude-sonnet-4-6"), ("claude-cli", 17, "claude-sonnet-5"))
        if name in providers)
    policy = tmp_path / "subllm.toml"
    policy.write_text(repository.read_text(encoding="utf-8").replace("\n[applications.", rows + "\n[applications.", 1),
                      encoding="utf-8")
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy))


def test_cli_providers_are_off_by_default_and_do_not_reach_shared_routes(monkeypatch):
    monkeypatch.delenv("SUBLLM_POLICY_FILE", raising=False)
    monkeypatch.delenv("SUBLLM_PROVIDER_ORDER", raising=False)
    providers = {r.provider for r in configured_routes("validator-agent", "direct-pr-review")}
    assert not providers & {"claude-cli", "agy-cli"}


def test_operator_opt_in_enables_routes_and_provider_order_still_gates(tmp_path, monkeypatch, fake_cli):
    fake_cli("claude", "pass\n")
    _enable(tmp_path, monkeypatch, "claude-cli", "agy-cli")
    monkeypatch.delenv("SUBLLM_PROVIDER_ORDER", raising=False)
    routes = {r.provider: r for r in configured_routes("validator-agent", "direct-pr-review")}
    assert routes["claude-cli"].transport == "claude-cli" and routes["claude-cli"].wire_model == "claude-sonnet-5"
    assert routes["agy-cli"].transport == "agy-cli" and routes["agy-cli"].wire_model == "claude-sonnet-4-6"
    # Only executors present on PATH become available routes; agy is missing here.
    available = {r.provider for r in available_routes(
        "validator-agent", "direct-pr-review", environ={"PATH": os.environ["PATH"]})}
    assert "claude-cli" in available and "agy-cli" not in available
    with pytest.raises(ValueError, match="local Claude Code login"):
        next(r for r in available_routes("validator-agent", "direct-pr-review",
                                         environ={"PATH": os.environ["PATH"]})
             if r.provider == "claude-cli").litellm_kwargs()
    monkeypatch.setenv("SUBLLM_PROVIDER_ORDER", "zai,openrouter")
    assert not {r.provider for r in configured_routes("validator-agent", "direct-pr-review")} & {
        "claude-cli", "agy-cli"}


def test_complete_dispatches_to_the_local_claude_login(tmp_path, monkeypatch, fake_cli):
    fake_cli("claude", CLAUDE_OK)
    _enable(tmp_path, monkeypatch, "claude-cli")
    monkeypatch.setenv("SUBLLM_PROVIDER_ORDER", "claude-cli")
    monkeypatch.setenv("SUBLLM_STATE_DIR", str(tmp_path / "state"))
    response = complete("validator-agent", "direct-pr-review", MESSAGES,
                        timeout_seconds=5, environ={"PATH": os.environ["PATH"], "SUBLLM_PROVIDER_ORDER": "claude-cli"})
    assert response.content == "answer"
    assert response.provider == "claude-cli" and response.model == "claude-sonnet-5"
