from __future__ import annotations

import json
from pathlib import Path

from subllm.cli import main


def test_check(capsys) -> None:
    assert main(["check"]) == 0
    assert capsys.readouterr().out == "SubLLM policy: OK\n"


def test_configured_field(capsys) -> None:
    assert (
        main(
            [
                "resolve",
                "validator-agent",
                "direct-pr-review",
                "--configured",
                "--provider",
                "openrouter",
                "--field",
                "litellm-model",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "openrouter/z-ai/glm-5.2\n"


def test_configured_application_name_field(capsys) -> None:
    assert (
        main(
            [
                "resolve",
                "platform",
                "interactive",
                "--configured",
                "--provider",
                "openrouter",
                "--field",
                "application-name",
            ]
        )
        == 0
    )
    assert capsys.readouterr().out == "Subactor Platform\n"


def test_resolve_output_never_contains_credential(tmp_path: Path, monkeypatch, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("OPENROUTER_API_KEY=or-cli-secret\n", encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.setenv("SUBLLM_ENV_FILE", str(env_file))
    monkeypatch.delenv("ZAI_API_KEY", raising=False)
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert main(["resolve", "repair-agent", "repair-plan"]) == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["provider"] == "openrouter"
    assert payload["model"] == "glm-5.2"
    assert payload["transport"] == "openai-compatible"
    assert "cli-secret" not in output


def test_env_check_reports_names_without_values(tmp_path: Path, monkeypatch, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ZAI_API_KEY=id.cli-secret\nOPENROUTER_API_KEY=\n", encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.setenv("SUBLLM_ENV_FILE", str(env_file))

    assert main(["env", "check"]) == 0
    output = capsys.readouterr().out
    assert output == "CURSOR_API_KEY: missing\nZAI_API_KEY: configured\nOPENROUTER_API_KEY: missing\n"
    assert "cli-secret" not in output


def test_providers_reports_effective_public_settings(capsys) -> None:
    assert main(["providers"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["providers"]["cursor"] == {
        "default_model": "gpt-5.6-sol",
        "enabled": True,
        "priority": 0,
    }
    assert payload["providers"]["zai"] == {
        "default_model": "glm-5.3",
        "enabled": True,
        "priority": 10,
    }
    assert payload["providers"]["openrouter"] == {
        "default_model": "glm-5.2",
        "enabled": True,
        "priority": 20,
    }


def test_providers_reports_explicit_order(monkeypatch, capsys) -> None:
    monkeypatch.setenv("SUBLLM_PROVIDER_ORDER", "openrouter,cursor,zai")
    assert main(["providers"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["order"] == ["openrouter", "cursor", "zai"]


def test_applications_reports_public_request_identity(capsys) -> None:
    assert main(["applications"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["applications"]["doctor-agent"] == {
        "name": "doctor-agent",
        "url": "https://github.com/subactor/doctor-agent",
    }
    assert payload["applications"]["todo2code"] == {
        "name": "todo2code",
        "url": "https://github.com/semcod/todo2code",
    }
