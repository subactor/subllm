from __future__ import annotations

import json
import subprocess
import sys
from types import ModuleType

import pytest

from subllm import CompletionError, client, complete, execute_code_edit
from subllm.client import CodeEditResponse, code_edit_main


class _Response:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_complete_executes_direct_zai_glm53_route(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def open_request(request, *, timeout):
        observed["url"] = request.full_url
        observed["authorization"] = request.get_header("Authorization")
        observed["body"] = json.loads(request.data.decode("utf-8"))
        observed["timeout"] = timeout
        return _Response(
            {
                "choices": [
                    {"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}
                ],
                "usage": {"total_tokens": 9},
            }
        )

    monkeypatch.setattr(client, "urlopen", open_request)
    result = complete(
        "todo2code",
        "semantic",
        [{"role": "user", "content": "Classify this change"}],
        request_id="todo2code-test-0001",
        timeout_seconds=12,
        environ={"ZAI_API_KEY": "id.secret"},
    )

    assert result.content == '{"ok":true}'
    assert result.provider == "zai"
    assert result.model == "glm-5.3"
    assert result.usage == {"total_tokens": 9}
    assert observed["url"] == "https://api.z.ai/api/coding/paas/v4/chat/completions"
    assert observed["authorization"] == "Bearer id.secret"
    assert observed["timeout"] == 12
    assert observed["body"] == {
        "model": "glm-5.3",
        "messages": [{"role": "user", "content": "Classify this change"}],
        "request_id": "todo2code-test-0001",
        "user_id": "todo2code",
    }
    assert "id.secret" not in repr(result)


def test_complete_dispatches_koru_cursor_route(monkeypatch, tmp_path) -> None:
    observed: dict[str, object] = {}

    def complete_cursor(route, messages, **kwargs):
        observed.update(route=route, messages=messages, **kwargs)
        return client.CompletionResponse(
            content="cursor answer",
            provider=route.provider,
            model=route.wire_model,
        )

    monkeypatch.setattr(client, "_complete_cursor", complete_cursor)
    result = complete(
        "koru-agent",
        "planning-assistant",
        [{"role": "user", "content": "x"}],
        environ={"CURSOR_API_KEY": "cursor_test-not-a-secret"},
        cwd=tmp_path,
    )

    assert result.content == "cursor answer"
    assert result.provider == "cursor"
    assert result.model == "gpt-5.6-sol"
    assert observed["cwd"] == tmp_path
    assert observed["messages"] == [{"role": "user", "content": "x"}]


def test_complete_cursor_uses_tool_free_sdk_with_caller_directory(monkeypatch, tmp_path) -> None:
    observed: dict[str, object] = {}

    class LocalAgentOptions:
        def __init__(self, **kwargs):
            observed["local"] = kwargs

    class AgentOptions:
        def __init__(self, **kwargs):
            observed["options"] = kwargs

    class Run:
        def supports(self, _feature: str) -> bool:
            return False

        def wait(self):
            return type(
                "Result",
                (),
                {
                    "status": "finished",
                    "result": "cursor answer",
                    "usage": {"total_tokens": 3},
                    "id": "run-1",
                },
            )()

    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def send(self, prompt: str):
            observed["prompt"] = prompt
            return Run()

    class Agent:
        @staticmethod
        def create(_options):
            return Session()

    module = ModuleType("cursor_sdk")
    module.Agent = Agent
    module.AgentOptions = AgentOptions
    module.LocalAgentOptions = LocalAgentOptions
    monkeypatch.setitem(sys.modules, "cursor_sdk", module)

    result = complete(
        "koru-agent",
        "planning-assistant",
        [{"role": "system", "content": "JSON only"}, {"role": "user", "content": "plan"}],
        environ={"CURSOR_API_KEY": "cursor_test-not-a-secret"},
        cwd=tmp_path,
    )

    assert result.content == "cursor answer"
    assert observed["options"]["tools"] == []
    assert observed["local"] == {"cwd": str(tmp_path), "setting_sources": []}
    assert "<system>\nJSON only\n</system>" in observed["prompt"]


def test_complete_executes_nfo_analysis_through_direct_zai(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def open_request(request, *, timeout):
        observed["body"] = json.loads(request.data.decode("utf-8"))
        return _Response(
            {
                "choices": [{"message": {"content": "root cause"}, "finish_reason": "stop"}],
                "usage": {"total_tokens": 5},
            }
        )

    monkeypatch.setattr(client, "urlopen", open_request)
    result = complete(
        "semcod-nfo",
        "analyze",
        [{"role": "user", "content": "Analyze this error"}],
        request_id="nfo-test-0001",
        environ={"ZAI_API_KEY": "id.secret"},
    )

    assert result.provider == "zai"
    assert result.model == "glm-5.3"
    assert result.content == "root cause"
    assert observed["body"] == {
        "model": "glm-5.3",
        "messages": [{"role": "user", "content": "Analyze this error"}],
        "request_id": "nfo-test-0001",
        "user_id": "semcod-nfo",
    }


def test_complete_rejects_empty_messages() -> None:
    with pytest.raises(CompletionError, match="at least one message"):
        complete("todo2code", "semantic", [], environ={"ZAI_API_KEY": "id.secret"})


def test_code_edit_routes_zai_credential_only_through_child_environment(monkeypatch, tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    observed: dict[str, object] = {}

    def run(command, **kwargs):
        observed["command"] = command
        observed.update(kwargs)
        return subprocess.CompletedProcess(command, 0, "Applied edit", "")

    monkeypatch.setattr(client.subprocess, "run", run)
    result = execute_code_edit(
        "onedev-agent",
        "code-edit",
        "Fix the governed ticket",
        worktree=tmp_path,
        provider="zai",
        environ={"ZAI_API_KEY": "id.secret"},
    )

    assert result.provider == "zai"
    assert result.model == "glm-5.3"
    assert result.response == "Applied edit"
    command = observed["command"]
    assert command[0] == "aider"
    assert "--no-auto-commits" in command
    assert "--no-auto-test" in command
    assert command[command.index("--map-tokens") + 1] == "0"
    assert "id.secret" not in repr(command)
    child_environment = observed["env"]
    assert child_environment["AIDER_OPENAI_API_KEY"] == "id.secret"
    assert child_environment["AIDER_OPENAI_API_BASE"] == "https://api.z.ai/api/coding/paas/v4"
    assert child_environment["AIDER_MODEL"] == "openai/glm-5.3"
    assert "id.secret" not in repr(result)


def test_code_edit_rejects_a_generic_executable(tmp_path) -> None:
    (tmp_path / ".git").mkdir()
    with pytest.raises(CompletionError, match="requires an aider executable"):
        execute_code_edit(
            "onedev-agent",
            "code-edit",
            "Fix it",
            worktree=tmp_path,
            aider_bin="sh",
            environ={"ZAI_API_KEY": "id.secret"},
        )


def test_code_edit_cli_emits_secret_free_machine_result(tmp_path, monkeypatch, capsys) -> None:
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Fix it", encoding="utf-8")
    monkeypatch.setattr(
        client,
        "execute_code_edit",
        lambda *_args, **_kwargs: CodeEditResponse("zai", "glm-5.3", "done"),
    )

    assert code_edit_main([
        "onedev-agent", "code-edit", "--worktree", str(tmp_path),
        "--prompt-file", str(prompt),
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "schema": "subllm.code-edit-result/v1",
        "status": "SUCCESS",
        "provider": "zai",
        "model": "glm-5.3",
        "response": "done",
    }
