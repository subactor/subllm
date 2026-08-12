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


def test_resolve_output_never_contains_credential(monkeypatch, capsys) -> None:
    monkeypatch.setenv("ZAI_API_KEY", "id.cli-secret")
    assert main(["resolve", "repair-agent", "repair-plan"]) == 0
    output = capsys.readouterr().out
    payload = json.loads(output)
    assert payload["provider"] == "zai"
    assert "cli-secret" not in output


def test_env_check_reports_names_without_values(tmp_path: Path, monkeypatch, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ZAI_API_KEY=id.cli-secret\nOPENROUTER_API_KEY=\n", encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.setenv("SUBLLM_ENV_FILE", str(env_file))

    assert main(["env", "check"]) == 0
    output = capsys.readouterr().out
    assert output == "ZAI_API_KEY: configured\nOPENROUTER_API_KEY: missing\n"
    assert "cli-secret" not in output
