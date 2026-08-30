from __future__ import annotations

import os
from pathlib import Path

import pytest

from subllm import (
    CURSOR_API_KEY_ENV,
    CredentialFileError,
    MissingCredentialError,
    credential_names,
    cursor_api_key,
    find_env_file,
    import_credentials,
    load_env_file,
    resolve,
)


def _private_file(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o600)
    return path


def test_workspace_discovery_and_process_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shared = tmp_path / "subllm" / ".env"
    shared.parent.mkdir()
    _private_file(shared, "ZAI_API_KEY=id.from-file\nOPENROUTER_API_KEY=or-file\n")
    application = tmp_path / "repair-agent"
    application.mkdir()
    monkeypatch.chdir(application)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-from-process")

    assert find_env_file() == shared
    route = resolve("repair-agent", "repair-plan")
    assert route.provider == "zai"
    assert route.api_key == "id.from-file"


def test_subactor_workspace_discovery_from_sibling_project(tmp_path: Path) -> None:
    shared = tmp_path / "subactor" / "subllm" / ".env"
    shared.parent.mkdir(parents=True)
    _private_file(shared, "CURSOR_API_KEY=cursor-workspace-key\n")
    project = tmp_path / "semcod" / "koru"
    project.mkdir(parents=True)

    assert find_env_file(cwd=project) == shared


def test_explicit_environment_keeps_resolution_hermetic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shared = tmp_path / "subllm" / ".env"
    shared.parent.mkdir()
    _private_file(shared, "ZAI_API_KEY=id.from-file\n")
    application = tmp_path / "doctor-agent"
    application.mkdir()
    monkeypatch.chdir(application)

    with pytest.raises(MissingCredentialError, match="no valid credential"):
        resolve("doctor-agent", "repair-proposal", environ={})


def test_explicit_file_path_can_be_relative(tmp_path: Path) -> None:
    shared = _private_file(tmp_path / "credentials.env", "OPENROUTER_API_KEY=or-value\n")
    assert find_env_file(environ={"SUBLLM_ENV_FILE": "credentials.env"}, cwd=tmp_path) == shared


def test_insecure_permissions_and_unknown_names_are_rejected(tmp_path: Path) -> None:
    insecure = _private_file(tmp_path / "insecure.env", "ZAI_API_KEY=id.secret\n")
    insecure.chmod(0o644)
    with pytest.raises(CredentialFileError, match="0600"):
        load_env_file(insecure)

    unknown = _private_file(tmp_path / "unknown.env", "UNRELATED=value\n")
    with pytest.raises(CredentialFileError, match="unsupported variable"):
        load_env_file(unknown)


def test_symbolic_link_is_rejected(tmp_path: Path) -> None:
    target = _private_file(tmp_path / "target.env", "ZAI_API_KEY=id.secret\n")
    link = tmp_path / "link.env"
    link.symlink_to(target)

    with pytest.raises(CredentialFileError, match="symbolic link"):
        load_env_file(link)


def test_import_merges_known_names_without_disclosing_values(tmp_path: Path) -> None:
    source_a = _private_file(tmp_path / "a.env", "OTHER=x\nZAI_API_KEY=id.secret\n")
    source_b = _private_file(tmp_path / "b.env", "OPENROUTER_API_KEY=or-secret\n")
    target = tmp_path / "subllm.env"

    assert import_credentials([source_a, source_b], target) == ("ZAI_API_KEY", "OPENROUTER_API_KEY")
    assert stat_mode(target) == 0o600
    assert load_env_file(target) == {
        "ZAI_API_KEY": "id.secret",
        "OPENROUTER_API_KEY": "or-secret",
    }


def test_import_rejects_conflicting_sources_without_creating_target(tmp_path: Path) -> None:
    source_a = _private_file(tmp_path / "a.env", "ZAI_API_KEY=id.one\n")
    source_b = _private_file(tmp_path / "b.env", "ZAI_API_KEY=id.two\n")
    target = tmp_path / "subllm.env"

    with pytest.raises(CredentialFileError, match="conflicting values"):
        import_credentials([source_a, source_b], target)
    assert not target.exists()


def test_credential_names_include_cursor_sdk_key() -> None:
    assert set(credential_names()) == {"ZAI_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CURSOR_API_KEY", "OLLAMA_API_KEY", "OPENROUTER_API_KEY"}
    assert CURSOR_API_KEY_ENV == "CURSOR_API_KEY"


def test_env_example_declares_empty_cursor_api_key() -> None:
    example = Path(__file__).resolve().parents[1] / ".env.example"
    assert example.is_file()
    assignments = {}
    for line in example.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, value = stripped.split("=", 1)
        assignments[name] = value
    assert assignments[CURSOR_API_KEY_ENV] == ""
    assert assignments["SUBLLM_PROVIDER_ORDER"] == ""
    assert all(not value.startswith("cursor_") for value in assignments.values())


def test_dotenv_is_gitignored() -> None:
    gitignore = Path(__file__).resolve().parents[1] / ".gitignore"
    names = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines() if line.strip()}
    assert ".env" in names


def test_cursor_api_key_loads_from_shared_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shared = tmp_path / "subllm" / ".env"
    shared.parent.mkdir()
    _private_file(shared, "CURSOR_API_KEY=cursor_test-not-a-secret\nZAI_API_KEY=id.secret\n")
    monkeypatch.chdir(tmp_path / "subllm")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)

    assert load_env_file(shared)[CURSOR_API_KEY_ENV] == "cursor_test-not-a-secret"
    assert cursor_api_key() == "cursor_test-not-a-secret"


def test_missing_cursor_api_key_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    shared = _private_file(tmp_path / ".env", "ZAI_API_KEY=id.secret\nCURSOR_API_KEY=\n")
    monkeypatch.setenv("SUBLLM_ENV_FILE", str(shared))
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)

    with pytest.raises(MissingCredentialError, match="CURSOR_API_KEY"):
        cursor_api_key()
    assert load_env_file(shared).get(CURSOR_API_KEY_ENV) == ""


def test_shared_file_accepts_provider_order(tmp_path: Path) -> None:
    path = _private_file(
        tmp_path / "order.env",
        "ZAI_API_KEY=id.secret\nSUBLLM_PROVIDER_ORDER=openrouter,zai\n",
    )
    assert load_env_file(path) == {
        "ZAI_API_KEY": "id.secret",
        "SUBLLM_PROVIDER_ORDER": "openrouter,zai",
    }


def test_import_accepts_cursor_api_key(tmp_path: Path) -> None:
    source = _private_file(tmp_path / "cursor.env", "CURSOR_API_KEY=cursor_test-not-a-secret\n")
    target = tmp_path / "subllm.env"

    assert import_credentials([source], target) == (CURSOR_API_KEY_ENV,)
    assert load_env_file(target) == {CURSOR_API_KEY_ENV: "cursor_test-not-a-secret"}


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777
