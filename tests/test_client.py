from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from subllm import CompletionError, client, complete, execute_code_edit, provider_health
from subllm.client import (
    CodeEditResponse,
    CompletionAttempt,
    CompletionResponse,
    code_edit_main,
    completion_main,
)


def _worker_success(content: str, *, usage: dict[str, object] | None = None) -> dict[str, object]:
    return {
        "schema": "subllm.openai-worker-result/v1",
        "status": "SUCCESS",
        "content": content,
        "usage": usage or {},
        "finish_reason": "stop",
    }


def test_complete_executes_direct_zai_glm53_route(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def run_worker(request, **kwargs):
        observed.update(request=request, **kwargs)
        return _worker_success('{"ok":true}', usage={"total_tokens": 9})

    monkeypatch.setattr(client, "_run_openai_worker", run_worker)
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
    assert observed["timeout_seconds"] == pytest.approx(12, abs=0.01)
    request = observed["request"]
    assert request["api_base"] == "https://api.z.ai/api/coding/paas/v4"
    assert request["wire_model"] == "glm-5.3"
    assert request["messages"] == [{"role": "user", "content": "Classify this change"}]
    assert request["request_fields"] == {"request_id": "todo2code-test-0001", "user_id": "todo2code"}
    assert "id.secret" not in repr(result)


def test_complete_sends_vision_image_parts_on_nexu_route(monkeypatch) -> None:
    observed: dict[str, object] = {}
    image = {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aaa"},
    }

    def run_worker(request, **kwargs):
        observed.update(request=request, **kwargs)
        return _worker_success("a button")

    monkeypatch.setattr(client, "_run_openai_worker", run_worker)
    result = complete(
        "autogrammar-nexu",
        "vision",
        [{"role": "user", "content": [image, {"type": "text", "text": "label this"}]}],
        environ={"OPENROUTER_API_KEY": "sk-or-v1-testkey"},
    )

    assert result.content == "a button"
    assert result.provider == "openrouter"
    assert result.model == "z-ai/glm-4.5v"
    request = observed["request"]
    assert request["api_base"] == "https://openrouter.ai/api/v1"
    assert request["messages"][0]["content"][0] == image
    assert request["wire_model"] == "z-ai/glm-4.5v"
    assert request["extra_headers"]["X-OpenRouter-Title"] == "nexu"


def test_complete_rejects_images_on_text_routes() -> None:
    with pytest.raises(CompletionError, match="vision SubLLM route"):
        complete(
            "autogrammar-nexu",
            "cinema",
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "data:image/png;base64,aaa"}},
                        {"type": "text", "text": "x"},
                    ],
                }
            ],
            environ={"OPENROUTER_API_KEY": "sk-or-v1-testkey"},
        )


def test_complete_rejects_vision_route_without_image() -> None:
    with pytest.raises(CompletionError, match="at least one image_url"):
        complete(
            "autogrammar-nexu",
            "vision",
            [{"role": "user", "content": "no image"}],
            environ={"OPENROUTER_API_KEY": "sk-or-v1-testkey"},
        )


def test_complete_rejects_file_image_urls() -> None:
    with pytest.raises(CompletionError, match="https or data:image"):
        complete(
            "autogrammar-nexu",
            "vision",
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": "file:///tmp/x.png"}},
                    ],
                }
            ],
            environ={"OPENROUTER_API_KEY": "sk-or-v1-testkey"},
        )


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

    def run_worker(request, **kwargs):
        observed.update(request=request, **kwargs)
        return {
            "schema": "subllm.cursor-worker-result/v1",
            "status": "SUCCESS",
            "content": "cursor answer",
            "usage": {"total_tokens": 3},
            "finish_reason": "",
            "run_id": "run-1",
        }

    monkeypatch.setattr(client, "_run_cursor_worker", run_worker)

    result = complete(
        "koru-agent",
        "planning-assistant",
        [{"role": "system", "content": "JSON only"}, {"role": "user", "content": "plan"}],
        environ={"CURSOR_API_KEY": "cursor_test-not-a-secret"},
        cwd=tmp_path,
    )

    assert result.content == "cursor answer"
    assert observed["cwd"] == tmp_path
    assert observed["timeout_seconds"] == 12
    request = observed["request"]
    assert request["cwd"] == str(tmp_path)
    assert request["model"] == "gpt-5.6-sol"
    assert "<system>\nJSON only\n</system>" in request["prompt"]


def test_cursor_worker_timeout_terminates_the_process_group(monkeypatch, tmp_path) -> None:
    observed: list[tuple[int, signal.Signals]] = []

    class Process:
        pid = 4312
        returncode = None
        waits = 0

        def communicate(self, **_kwargs):
            raise subprocess.TimeoutExpired([sys.executable], 0.1)

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired([sys.executable], timeout)
            self.returncode = -signal.SIGKILL
            return self.returncode

    process = Process()
    monkeypatch.setattr(client.subprocess, "Popen", lambda *_args, **_kwargs: process)
    monkeypatch.setattr(client.os, "killpg", lambda pid, sig: observed.append((pid, sig)))

    with pytest.raises(CompletionError, match="worker timed out"):
        client._run_cursor_worker(
            {"schema": "subllm.cursor-worker-request/v1"},
            timeout_seconds=0.1,
            cwd=tmp_path,
        )

    assert observed == [(4312, signal.SIGTERM), (4312, signal.SIGKILL)]


def test_cursor_worker_timeout_reaps_real_descendant(monkeypatch, tmp_path) -> None:
    assert os.name == "posix", "the governed completion runtime requires POSIX process groups"
    child_pid_file = tmp_path / "cursor-child.pid"
    source_root = Path(client.__file__).resolve().parents[1]
    fixture_root = Path(__file__).resolve().parent / "fixtures" / "hanging_cursor_sdk"
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join((str(fixture_root), str(source_root))))
    monkeypatch.setenv("SUBLLM_TEST_CHILD_PID_FILE", str(child_pid_file))

    with pytest.raises(CompletionError, match="worker timed out"):
        client._run_cursor_worker(
            {
                "schema": "subllm.cursor-worker-request/v1",
                "model": "gpt-5.6-sol",
                "api_key": "cursor_test-not-a-secret",
                "cwd": str(tmp_path),
                "name": "subllm-timeout-test",
                "prompt": "wait",
            },
            timeout_seconds=1.0,
            cwd=tmp_path,
        )

    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"Cursor worker descendant {child_pid} remained alive")


def test_openai_worker_deadline_reaps_real_descendant(monkeypatch, tmp_path) -> None:
    assert os.name == "posix", "the governed completion runtime requires POSIX process groups"
    child_pid_file = tmp_path / "openai-child.pid"
    fixture_root = Path(__file__).resolve().parent / "fixtures" / "hanging_openai_worker"
    monkeypatch.setenv("PYTHONPATH", str(fixture_root))
    monkeypatch.setenv("SUBLLM_TEST_CHILD_PID_FILE", str(child_pid_file))

    with pytest.raises(CompletionError, match="worker timed out"):
        client._run_openai_worker(
            {"schema": "subllm.openai-worker-request/v1"},
            timeout_seconds=1.0,
        )

    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail(f"OpenAI worker descendant {child_pid} remained alive")


def test_complete_executes_nfo_analysis_through_direct_zai(monkeypatch) -> None:
    observed: dict[str, object] = {}

    def run_worker(request, **kwargs):
        observed.update(request=request, **kwargs)
        return _worker_success("root cause", usage={"total_tokens": 5})

    monkeypatch.setattr(client, "_run_openai_worker", run_worker)
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
    assert observed["request"]["wire_model"] == "glm-5.3"
    assert observed["request"]["messages"] == [{"role": "user", "content": "Analyze this error"}]
    assert observed["request"]["request_fields"] == {
        "request_id": "nfo-test-0001", "user_id": "semcod-nfo",
    }


def test_complete_rejects_empty_messages() -> None:
    with pytest.raises(CompletionError, match="at least one message"):
        complete("todo2code", "semantic", [], environ={"ZAI_API_KEY": "id.secret"})


def test_complete_forwards_structured_response_format(monkeypatch) -> None:
    observed = {}

    def run_worker(request, **kwargs):
        observed.update(request=request, **kwargs)
        return _worker_success("{}")

    monkeypatch.setattr(client, "_run_openai_worker", run_worker)
    complete(
        "autogrammar-hillm",
        "invoke",
        [{"role": "user", "content": "translate"}],
        response_format={"type": "json_object"},
        environ={"ZAI_API_KEY": "id.secret"},
    )

    assert observed["request"]["response_format"] == {"type": "json_object"}


def test_complete_fails_over_after_provider_timeout_and_reports_attempts(monkeypatch) -> None:
    providers: list[str] = []

    def run_worker(request, **_kwargs):
        providers.append(request["api_base"])
        if request["provider"] == "zai":
            return {
                "schema": "subllm.openai-worker-result/v1",
                "status": "ERROR",
                "outcome": "timeout",
                "provider_level": True,
                "retryable": True,
            }
        return _worker_success("fallback")

    monkeypatch.setattr(client, "_run_openai_worker", run_worker)
    result = complete(
        "repair-agent",
        "repair-plan",
        [{"role": "user", "content": "repair"}],
        timeout_seconds=20,
        environ={
            "ZAI_API_KEY": "id.secret",
            "OPENROUTER_API_KEY": "sk-or-v1-testkey",
        },
    )

    assert result.provider == "openrouter"
    assert result.model == "z-ai/glm-5.3"
    assert [attempt.outcome for attempt in result.attempts] == ["timeout", "success"]
    assert providers == [
        "https://api.z.ai/api/coding/paas/v4",
        "https://openrouter.ai/api/v1",
    ]
    zai = next(receipt for receipt in provider_health() if receipt.provider == "zai")
    assert zai.status == "degraded"
    assert zai.reason == "timeout"


def test_complete_prefers_healthy_provider_during_cooldown(monkeypatch) -> None:
    providers: list[str] = []
    failures = 0

    def run_worker(request, **_kwargs):
        nonlocal failures
        providers.append(request["api_base"])
        if failures == 0:
            failures += 1
            return {
                "schema": "subllm.openai-worker-result/v1",
                "status": "ERROR",
                "outcome": "timeout",
                "provider_level": True,
                "retryable": True,
            }
        return _worker_success("ok")

    monkeypatch.setattr(client, "_run_openai_worker", run_worker)
    credentials = {
        "ZAI_API_KEY": "id.secret",
        "OPENROUTER_API_KEY": "sk-or-v1-testkey",
    }
    complete(
        "todo2code",
        "semantic",
        [{"role": "user", "content": "first"}],
        timeout_seconds=20,
        environ=credentials,
    )
    providers.clear()

    result = complete(
        "todo2code",
        "semantic",
        [{"role": "user", "content": "second"}],
        timeout_seconds=20,
        environ=credentials,
    )

    assert result.provider == "openrouter"
    assert providers == ["https://openrouter.ai/api/v1"]


def test_complete_does_not_replay_non_retryable_bad_request(monkeypatch) -> None:
    calls = 0

    def run_worker(_request, **_kwargs):
        nonlocal calls
        calls += 1
        return {
            "schema": "subllm.openai-worker-result/v1",
            "status": "ERROR",
            "outcome": "http_400",
            "provider_level": True,
            "retryable": False,
        }

    monkeypatch.setattr(client, "_run_openai_worker", run_worker)
    with pytest.raises(CompletionError, match="HTTP 400"):
        complete(
            "todo2code",
            "semantic",
            [{"role": "user", "content": "bad"}],
            environ={
                "ZAI_API_KEY": "id.secret",
                "OPENROUTER_API_KEY": "sk-or-v1-testkey",
            },
        )

    assert calls == 1


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


def test_completion_cli_executes_policy_transport_and_emits_attempt_receipt(
    monkeypatch, capsys,
) -> None:
    request = {
        "schema": "subllm.completion-request/v1",
        "messages": [{"role": "user", "content": "assess"}],
        "response_format": {"type": "json_object"},
        "request_id": "supervisor-test-1",
    }
    monkeypatch.setattr(
        client.sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO(json.dumps(request).encode())),
    )
    observed: dict[str, object] = {}

    def run_complete(application, function, messages, **kwargs):
        observed.update(application=application, function=function, messages=messages, **kwargs)
        return CompletionResponse(
            content='{"action":"observe"}',
            provider="cursor",
            model="gpt-5.6-sol",
            usage={"total_tokens": 7},
            finish_reason="stop",
            attempts=(CompletionAttempt("zai", "glm-5.3", "http_429", 12),),
        )

    monkeypatch.setattr(client, "complete", run_complete)
    assert completion_main(["supervisor", "assessment", "--timeout", "120"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "schema": "subllm.completion-result/v1",
        "status": "SUCCESS",
        "content": '{"action":"observe"}',
        "provider": "cursor",
        "model": "gpt-5.6-sol",
        "usage": {"total_tokens": 7},
        "finish_reason": "stop",
        "attempts": [
            {"provider": "zai", "model": "glm-5.3", "outcome": "http_429", "duration_ms": 12}
        ],
    }
    assert observed == {
        "application": "supervisor",
        "function": "assessment",
        "messages": request["messages"],
        "timeout_seconds": 120.0,
        "request_id": "supervisor-test-1",
        "response_format": {"type": "json_object"},
    }


@pytest.mark.parametrize(
    "payload_input,error",
    [
        ({"schema": "subllm.completion-request/v1", "messages": [], "extra": True}, "closed JSON object"),
        ({"schema": "other/v1", "messages": [{"role": "user"}]}, "schema is not supported"),
    ],
)
def test_completion_cli_rejects_unbounded_or_unknown_input(
    monkeypatch, capsys, payload_input, error,
) -> None:
    monkeypatch.setattr(
        client.sys,
        "stdin",
        SimpleNamespace(buffer=io.BytesIO(json.dumps(payload_input).encode())),
    )
    assert completion_main(["supervisor", "assessment"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert error in captured.err
