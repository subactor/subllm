from __future__ import annotations

import json

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

