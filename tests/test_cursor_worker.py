from __future__ import annotations

import sys
from types import ModuleType

from subllm import cursor_worker


def test_execute_uses_tool_free_cursor_sdk_in_declared_directory(monkeypatch, tmp_path) -> None:
    observed: dict[str, object] = {}

    class LocalAgentOptions:
        def __init__(self, **kwargs):
            observed["local"] = kwargs

    class AgentOptions:
        def __init__(self, **kwargs):
            observed["options"] = kwargs

    class Run:
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

    result = cursor_worker._execute({
        "model": "gpt-5.6-sol",
        "api_key": "cursor_test-not-a-secret",
        "cwd": str(tmp_path),
        "name": "subllm-supervisor-assessment",
        "prompt": "Return JSON",
    })

    assert result["content"] == "cursor answer"
    assert observed["options"]["tools"] == []
    assert observed["local"] == {"cwd": str(tmp_path), "setting_sources": []}
    assert observed["prompt"] == "Return JSON"
    assert "cursor_test-not-a-secret" not in repr(result)
