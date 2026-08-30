from __future__ import annotations

import io
import json
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from urllib.error import HTTPError

import pytest

from subllm import (
    PROVIDER_CHAIN_EXHAUSTED_CODE,
    PROVIDER_RATE_LIMIT_CODE,
    PROVIDER_UNAVAILABLE_CODE,
    CompletionError,
    client,
    complete,
    execute_code_edit,
    provider_health,
)
from subllm.client import (
    CodeEditResponse,
    CompletionAttempt,
    CompletionResponse,
    code_edit_main,
    completion_main,
)


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
    assert observed["timeout"] == pytest.approx(12, abs=0.01)
    assert observed["body"] == {
        "model": "glm-5.3",
        "messages": [{"role": "user", "content": "Classify this change"}],
        "request_id": "todo2code-test-0001",
        "user_id": "todo2code",
    }
    assert "id.secret" not in repr(result)


def test_complete_sends_vision_image_parts_on_nexu_route(monkeypatch) -> None:
    observed: dict[str, object] = {}
    image = {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,aaa"},
    }

    def open_request(request, *, timeout):
        observed["url"] = request.full_url
        observed["title"] = request.get_header("X-openrouter-title")
        observed["body"] = json.loads(request.data.decode("utf-8"))
        return _Response(
            {
                "choices": [{"message": {"content": "a button"}, "finish_reason": "stop"}],
            }
        )

    monkeypatch.setattr(client, "urlopen", open_request)
    result = complete(
        "autogrammar-nexu",
        "vision",
        [{"role": "user", "content": [image, {"type": "text", "text": "label this"}]}],
        environ={"OPENROUTER_API_KEY": "sk-or-v1-testkey"},
    )

    assert result.content == "a button"
    assert result.provider == "openrouter"
    assert result.model == "z-ai/glm-4.5v"
    assert observed["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert observed["body"]["messages"][0]["content"][0] == image
    assert observed["body"]["model"] == "z-ai/glm-4.5v"


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


def test_complete_forwards_structured_response_format(monkeypatch) -> None:
    observed = {}

    def open_request(request, timeout):
        observed["body"] = json.loads(request.data.decode("utf-8"))
        return _Response(
            {"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]}
        )

    monkeypatch.setattr(client, "urlopen", open_request)
    complete(
        "autogrammar-hillm",
        "invoke",
        [{"role": "user", "content": "translate"}],
        response_format={"type": "json_object"},
        environ={"ZAI_API_KEY": "id.secret"},
    )

    assert observed["body"]["response_format"] == {"type": "json_object"}


def test_complete_fails_over_after_provider_timeout_and_reports_attempts(monkeypatch) -> None:
    providers: list[str] = []

    def open_request(request, *, timeout):
        providers.append(request.full_url)
        if "api.z.ai" in request.full_url:
            raise TimeoutError("simulated stall")
        return _Response(
            {"choices": [{"message": {"content": "fallback"}, "finish_reason": "stop"}]}
        )

    monkeypatch.setattr(client, "urlopen", open_request)
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
    assert [attempt.diagnostic_code for attempt in result.attempts] == [
        PROVIDER_UNAVAILABLE_CODE,
        None,
    ]
    assert providers == [
        "https://api.z.ai/api/coding/paas/v4/chat/completions",
        "https://openrouter.ai/api/v1/chat/completions",
    ]
    zai = next(receipt for receipt in provider_health() if receipt.provider == "zai")
    assert zai.status == "degraded"
    assert zai.reason == "timeout"


def test_complete_codes_rate_limit_before_successful_failover(monkeypatch) -> None:
    providers: list[str] = []

    def open_request(request, *, timeout):
        providers.append(request.full_url)
        if "api.z.ai" in request.full_url:
            raise HTTPError(request.full_url, 429, "rate limited", {}, None)
        return _Response(
            {"choices": [{"message": {"content": "fallback"}, "finish_reason": "stop"}]}
        )

    monkeypatch.setattr(client, "urlopen", open_request)
    result = complete(
        "todo2code",
        "semantic",
        [{"role": "user", "content": "classify"}],
        timeout_seconds=20,
        environ={
            "ZAI_API_KEY": "id.secret",
            "OPENROUTER_API_KEY": "sk-or-v1-testkey",
        },
    )

    assert result.provider == "openrouter"
    assert [attempt.diagnostic_code for attempt in result.attempts] == [
        PROVIDER_RATE_LIMIT_CODE,
        None,
    ]
    assert len(providers) == 2


def test_complete_codes_exhausted_bounded_provider_chain(monkeypatch) -> None:
    calls = 0

    def open_request(request, *, timeout):
        nonlocal calls
        calls += 1
        raise TimeoutError("simulated provider outage")

    monkeypatch.setattr(client, "urlopen", open_request)
    with pytest.raises(CompletionError, match="all bounded candidates failed") as raised:
        complete(
            "todo2code",
            "semantic",
            [{"role": "user", "content": "classify"}],
            timeout_seconds=20,
            environ={
                "ZAI_API_KEY": "id.secret",
                "OPENROUTER_API_KEY": "sk-or-v1-testkey",
            },
        )

    assert raised.value.diagnostic_code == PROVIDER_CHAIN_EXHAUSTED_CODE
    assert calls == 2


def test_complete_prefers_healthy_provider_during_cooldown(monkeypatch) -> None:
    providers: list[str] = []
    failures = 0

    def open_request(request, *, timeout):
        nonlocal failures
        providers.append(request.full_url)
        if failures == 0:
            failures += 1
            raise TimeoutError("simulated stall")
        return _Response(
            {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
        )

    monkeypatch.setattr(client, "urlopen", open_request)
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
    assert providers == ["https://openrouter.ai/api/v1/chat/completions"]


def test_complete_does_not_replay_non_retryable_bad_request(monkeypatch) -> None:
    calls = 0

    def open_request(request, *, timeout):
        nonlocal calls
        calls += 1
        raise HTTPError(request.full_url, 400, "bad request", {}, None)

    monkeypatch.setattr(client, "urlopen", open_request)
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
            attempts=(CompletionAttempt(
                "zai",
                "glm-5.3",
                "http_429",
                12,
                PROVIDER_RATE_LIMIT_CODE,
            ),),
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
            {
                "provider": "zai",
                "model": "glm-5.3",
                "outcome": "http_429",
                "duration_ms": 12,
                "diagnostic_code": PROVIDER_RATE_LIMIT_CODE,
            }
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
