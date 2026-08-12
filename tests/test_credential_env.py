from __future__ import annotations

import os
from pathlib import Path

import pytest

from subllm import (
    CredentialFileError,
    MissingCredentialError,
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
    monkeypatch.setenv("ZAI_API_KEY", "id.from-process")

    assert find_env_file() == shared
    route = resolve("repair-agent", "repair-plan")
    assert route.api_key == "id.from-process"


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


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777
