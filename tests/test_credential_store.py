"""Credential file management: never leaks a value, always leaves a file the runtime accepts."""
from __future__ import annotations

import io
import stat
import urllib.error

import pytest

from subllm import credential_store as store
from subllm.cli import main
from subllm.credential_env import load_env_file
from subllm.credential_template import PRESETS, render
from subllm.errors import CredentialFileError, InvalidPolicyError

SECRET = "AQ.Ab8RN6" + "x" * 44


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# my notes\nZAI_API_KEY=\nOPENROUTER_API_KEY=test-or-key-value-1234\nSUBLLM_PROVIDER_ORDER=zai,openrouter\n"
    )
    path.chmod(0o600)
    return path


def test_template_is_accepted_by_the_runtime_loader_and_lists_every_key(tmp_path):
    path = tmp_path / ".env"
    path.write_text(render())
    path.chmod(0o600)
    loaded = load_env_file(path)
    assert loaded["SUBLLM_PROVIDER_ORDER"] == PRESETS["balanced"][0]
    assert {"GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ZAI_API_KEY", "CURSOR_API_KEY",
            "OLLAMA_API_KEY", "OPENROUTER_API_KEY"} <= set(loaded)
    for name in PRESETS:
        assert f"# {name}:" in render()


def test_every_preset_is_a_valid_provider_order():
    from subllm.provider_order import parse_provider_order
    for order, _note in PRESETS.values():
        parse_provider_order(order)


def test_set_replaces_or_adds_keeps_everything_else_and_backs_up(env_file):
    backup = store.set_value(env_file, "GEMINI_API_KEY", SECRET)
    text = env_file.read_text()
    assert text.startswith("# my notes\n") and "OPENROUTER_API_KEY=test-or-key-value-1234" in text
    assert text.count("GEMINI_API_KEY=") == 1 and f"GEMINI_API_KEY={SECRET}" in text
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert backup is not None and stat.S_IMODE(backup.stat().st_mode) == 0o600
    assert "GEMINI_API_KEY" not in backup.read_text()  # the backup is the previous state
    store.set_value(env_file, "GEMINI_API_KEY", "z" * 40)  # replace, no duplicate line
    assert env_file.read_text().count("GEMINI_API_KEY=") == 1
    assert load_env_file(env_file)["GEMINI_API_KEY"] == "z" * 40


@pytest.mark.parametrize(
    "value", ["", "short", "has space in it 1234", 'quo"te12345', "dollar$1234567", "PLACEHOLDER-value"]
)
def test_bad_values_are_rejected_without_touching_the_file(env_file, value):
    before = env_file.read_text()
    with pytest.raises(CredentialFileError):
        store.set_value(env_file, "GEMINI_API_KEY", value)
    assert env_file.read_text() == before


def test_zai_needs_its_id_dot_secret_format(env_file):
    with pytest.raises(CredentialFileError):
        store.set_value(env_file, "ZAI_API_KEY", "no-dot-in-this-value")
    store.set_value(env_file, "ZAI_API_KEY", "id123456.secret1234")


def test_loose_permissions_or_symlink_or_unknown_variable_are_refused(tmp_path, env_file):
    env_file.chmod(0o644)
    with pytest.raises(CredentialFileError):
        store.set_value(env_file, "GEMINI_API_KEY", SECRET)
    env_file.chmod(0o600)
    with pytest.raises(CredentialFileError):
        store.set_value(env_file, "NOT_A_KEY", SECRET)
    link = tmp_path / "link.env"
    link.symlink_to(env_file)
    with pytest.raises(CredentialFileError):
        store.set_value(link, "GEMINI_API_KEY", SECRET)
    env_file.write_text("SOMETHING_ELSE=1\n")
    with pytest.raises(CredentialFileError):  # the runtime would reject this file, so it is not edited
        store.set_value(env_file, "GEMINI_API_KEY", SECRET)


def test_unset_and_order(env_file):
    store.unset_value(env_file, "OPENROUTER_API_KEY")
    assert load_env_file(env_file)["OPENROUTER_API_KEY"] == ""
    store.set_order(env_file, "agy,zai,openrouter")
    assert store.current_order(env_file) == "agy,zai,openrouter"
    with pytest.raises(InvalidPolicyError, match="unknown provider"):
        store.set_order(env_file, "agy,nonsense")
    with pytest.raises(InvalidPolicyError, match="duplicate"):
        store.set_order(env_file, "agy,agy")
    store.set_order(env_file, "")
    assert store.current_order(env_file) == ""


def test_describe_reports_state_never_the_value(env_file):
    store.set_value(env_file, "GEMINI_API_KEY", SECRET)
    states = {s.variable: s for s in store.describe(env_file)}
    assert states["GEMINI_API_KEY"].state == "set" and states["GEMINI_API_KEY"].length == len(SECRET)
    assert states["ZAI_API_KEY"].state == "empty" and states["ANTHROPIC_API_KEY"].state == "absent"
    assert SECRET not in repr(states)


class _Opener:
    def __init__(self, error=None):
        self.error = error

    def open(self, request, timeout=None):
        if self.error:
            raise self.error
        return io.BytesIO(b"{}")


@pytest.mark.parametrize(("error", "status"), [
    (None, "ok"),
    (urllib.error.HTTPError("https://x", 401, "n", {}, None), "invalid"),
    (urllib.error.HTTPError("https://x", 403, "n", {}, None), "invalid"),
    (urllib.error.HTTPError("https://x", 429, "n", {}, None), "limited"),
    (urllib.error.HTTPError("https://x", 404, "n", {}, None), "unsupported"),
    (urllib.error.HTTPError("https://x", 500, "n", {}, None), "unreachable"),
    (urllib.error.URLError("down"), "unreachable"),
])
def test_verify_maps_provider_answers_and_never_echoes_the_key(monkeypatch, error, status):
    seen = {}

    def opener(*args):
        return type("O", (), {"open": lambda self, request, timeout=None: (seen.update(h=dict(request.header_items()),
                              u=request.full_url), _Opener(error).open(request))[1]})()

    monkeypatch.setattr(store.urllib.request, "build_opener", opener)
    result = store.verify_key("GEMINI_API_KEY", SECRET)
    assert result.status == status and SECRET not in repr(result)
    assert SECRET not in seen["u"]  # the key is sent as a header, not in the URL


def test_verify_without_value_or_endpoint():
    assert store.verify_key("GEMINI_API_KEY", "").status == "missing"
    assert store.verify_key("CURSOR_API_KEY", "x" * 20).status == "unsupported"


def test_cli_set_list_verify_order_end_to_end(env_file, monkeypatch, capsys):
    monkeypatch.setattr(store.urllib.request, "build_opener", lambda *a: _Opener())
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    assert main(["env", "set", "agy", "--stdin", "--file", str(env_file)]) == 0
    out = capsys.readouterr().out
    assert "GEMINI_API_KEY: ok" in out and SECRET not in out
    assert main(["env", "list", "--file", str(env_file)]) == 0
    listing = capsys.readouterr().out
    assert "GEMINI_API_KEY" in listing and " set " in listing and SECRET not in listing
    assert main(["env", "verify", "--file", str(env_file)]) == 0
    assert SECRET not in capsys.readouterr().out
    assert main(["env", "order", "--preset", "high-performance", "--file", str(env_file)]) == 0
    assert store.current_order(env_file) == PRESETS["high-performance"][0]
    assert main(["env", "unset", "agy", "--file", str(env_file)]) == 0
    assert load_env_file(env_file)["GEMINI_API_KEY"] == ""


def test_cli_set_refuses_a_rejected_key_and_a_missing_terminal(env_file, monkeypatch, capsys):
    rejected = urllib.error.HTTPError("https://x", 401, "n", {}, None)
    monkeypatch.setattr(store.urllib.request, "build_opener", lambda *a: _Opener(rejected))
    monkeypatch.setattr("sys.stdin", io.StringIO(SECRET + "\n"))
    before = env_file.read_text()
    assert main(["env", "set", "agy", "--stdin", "--file", str(env_file)]) != 0
    assert env_file.read_text() == before
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert main(["env", "set", "agy", "--file", str(env_file)]) != 0  # no tty, no --stdin
    assert SECRET not in capsys.readouterr().out


def test_cli_template_prints_the_annotated_file(capsys):
    assert main(["env", "template"]) == 0
    assert "GEMINI_API_KEY=" in capsys.readouterr().out
