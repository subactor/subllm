from __future__ import annotations

import json
from pathlib import Path

import pytest

from subllm.cli import _parser, dispatch, main
from subllm.errors import SubLLMError
from subllm.poa.refs import ROUTE_INPUT
from subllm.poa.registry import (
    CONFIGURED_ROUTE_URI,
    CREATE_PLAN_URI,
    EXPORT_CONTRACT_URI,
    IMPORT_CREDENTIALS_URI,
    LIST_ROUTES_URI,
    OBSERVE_CREDENTIALS_URI,
    RESOLVE_ROUTE_URI,
    VALIDATE_URI,
)


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
    assert capsys.readouterr().out == "openrouter/z-ai/glm-5.3-flash\n"


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
    assert payload["model"] == "glm-5.3"
    assert payload["transport"] == "openai-compatible"
    assert "cli-secret" not in output


def test_env_check_reports_names_without_values(tmp_path: Path, monkeypatch, capsys) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("ZAI_API_KEY=id.cli-secret\nOPENROUTER_API_KEY=\n", encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.setenv("SUBLLM_ENV_FILE", str(env_file))

    assert main(["env", "check"]) == 0
    output = capsys.readouterr().out
    assert "ZAI_API_KEY: configured" in output
    assert "OPENROUTER_API_KEY: missing" in output
    assert "CURSOR_API_KEY: missing" in output
    assert "GEMINI_API_KEY: missing" in output
    assert "OPENAI_API_KEY: missing" in output
    assert "ANTHROPIC_API_KEY: missing" in output
    assert "OLLAMA_API_KEY: missing" in output
    assert "cli-secret" not in output


def test_providers_reports_effective_public_settings(capsys) -> None:
    assert main(["providers"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["providers"]["cursor"] == {
        "default_model": "gpt-5.6-sol",
        "enabled": False,
        "priority": 20,
    }
    assert payload["providers"]["zai"] == {
        "default_model": "glm-5.3",
        "enabled": True,
        "priority": 0,
    }
    assert payload["providers"]["openrouter"] == {
        "default_model": "glm-5.3-flash",
        "enabled": True,
        "priority": 30,
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
        "url": "https://github.com/autogrammar/todo2code",
    }


class _FakeBus:
    """Records CQRS traffic so dispatch routing is asserted without policy I/O."""

    def __init__(self, query_results=None, command_results=None) -> None:
        self.queries: list[dict] = []
        self.commands: list[dict] = []
        self.inspect_refs: list[str] = []
        self._query_results = query_results or {}
        self._command_results = command_results or {}

    def query(self, document: dict) -> dict:
        self.queries.append(document)
        return self._query_results[document["process_uri"]]

    def command(self, document: dict) -> dict:
        self.commands.append(document)
        return self._command_results.get(document["process_uri"], {"result": {"imported": []}})

    def inspect(self, process_ref: str) -> dict:
        self.inspect_refs.append(process_ref)
        return {"schema": "poa.request/v1"}


def test_parser_keeps_resolve_surface() -> None:
    args = _parser().parse_args(["resolve", "app", "fn", "--configured", "--field", "provider"])
    assert (args.command, args.application, args.function) == ("resolve", "app", "fn")
    assert args.configured is True
    assert args.provider is None


def test_parser_rejects_unknown_resolve_field() -> None:
    with pytest.raises(SystemExit) as excinfo:
        _parser().parse_args(["resolve", "app", "fn", "--field", "secret"])
    assert excinfo.value.code == 2


def test_parser_defaults_for_env_import_serve_and_poa_plan() -> None:
    env_args = _parser().parse_args(["env", "import", "a.env"])
    assert env_args.env_command == "import"
    assert env_args.target.name == ".env"
    serve_args = _parser().parse_args(["serve"])
    assert (serve_args.host, serve_args.port) == ("127.0.0.1", 8788)
    plan_args = _parser().parse_args(["poa", "plan", "subllm.resolve-route"])
    assert plan_args.subject == "service:subllm-cli"
    assert plan_args.idempotency_key is None


def test_dispatch_check_queries_validate_uri(capsys) -> None:
    bus = _FakeBus(query_results={VALIDATE_URI: {"status": "ok"}})
    assert dispatch(bus, _parser().parse_args(["check"])) == 0
    assert bus.queries == [{"schema": "subllm.query/v1", "process_uri": VALIDATE_URI}]
    assert capsys.readouterr().out == "SubLLM policy: OK\n"


def test_dispatch_resolve_uses_live_or_configured_uri(capsys) -> None:
    live = _FakeBus(query_results={RESOLVE_ROUTE_URI: {"provider": "openrouter"}})
    assert dispatch(live, _parser().parse_args(["resolve", "app", "fn"])) == 0
    assert live.queries[0]["process_uri"] == RESOLVE_ROUTE_URI
    assert json.loads(capsys.readouterr().out) == {"provider": "openrouter"}
    configured = _FakeBus(query_results={CONFIGURED_ROUTE_URI: {"provider": "openrouter"}})
    assert dispatch(configured, _parser().parse_args(["resolve", "app", "fn", "--configured"])) == 0
    assert configured.queries[0]["process_uri"] == CONFIGURED_ROUTE_URI


def test_dispatch_resolve_field_maps_dashes_to_underscores(capsys) -> None:
    bus = _FakeBus(query_results={RESOLVE_ROUTE_URI: {"api_key_env": "ZAI_API_KEY"}})
    args = _parser().parse_args(["resolve", "app", "fn", "--field", "api-key-env"])
    assert dispatch(bus, args) == 0
    assert capsys.readouterr().out == "ZAI_API_KEY\n"


def test_dispatch_env_check_prints_states(capsys) -> None:
    results = {OBSERVE_CREDENTIALS_URI: {"path": "/tmp/.env", "credentials": {"ZAI_API_KEY": "configured"}}}
    bus = _FakeBus(query_results=results)
    assert dispatch(bus, _parser().parse_args(["env", "check"])) == 0
    assert capsys.readouterr().out == "ZAI_API_KEY: configured\n"


def test_dispatch_env_path_without_file_raises_domain_error() -> None:
    results = {OBSERVE_CREDENTIALS_URI: {"path": None, "credentials": {}}}
    bus = _FakeBus(query_results=results)
    with pytest.raises(SubLLMError):
        dispatch(bus, _parser().parse_args(["env", "path"]))


def test_dispatch_env_import_sends_closed_command(capsys) -> None:
    bus = _FakeBus(command_results={IMPORT_CREDENTIALS_URI: {"result": {"imported": ["ZAI_API_KEY"]}}})
    args = _parser().parse_args(["env", "import", "a.env", "--target", "b.env"])
    assert dispatch(bus, args) == 0
    command = bus.commands[0]
    assert command["schema"] == "subllm.command/v1"
    assert command["process_uri"] == IMPORT_CREDENTIALS_URI
    assert command["sources"] == ["a.env"]
    assert command["target"] == "b.env"
    assert command["subject"] == "service:subllm-cli"
    assert command["idempotency_key"].startswith("cli.import.")
    expected_target = Path("b.env").resolve(strict=False)
    assert capsys.readouterr().out == f"Imported ZAI_API_KEY into {expected_target}\n"


def test_dispatch_poa_plan_builds_bound_command() -> None:
    bus = _FakeBus()
    args = _parser().parse_args(["poa", "plan", "subllm.resolve-route"])
    assert dispatch(bus, args) == 0
    command = bus.commands[0]
    assert command["process_uri"] == CREATE_PLAN_URI
    assert command["process_ref"] == "subllm.resolve-route"
    assert command["input_ref"] == ROUTE_INPUT
    assert command["input_sha256"]
    assert command["subject"] == "service:subllm-cli"
    assert command["idempotency_key"].startswith("cli.plan.")


def test_dispatch_poa_catalog_does_not_touch_bus(capsys) -> None:
    bus = _FakeBus()
    assert dispatch(bus, _parser().parse_args(["poa", "catalog"])) == 0
    assert bus.queries == [] and bus.commands == [] and bus.inspect_refs == []
    assert isinstance(json.loads(capsys.readouterr().out), dict)


def test_dispatch_poa_inspect_uses_bus(capsys) -> None:
    bus = _FakeBus()
    assert dispatch(bus, _parser().parse_args(["poa", "inspect", "subllm.resolve-route"])) == 0
    assert bus.inspect_refs == ["subllm.resolve-route"]
    assert json.loads(capsys.readouterr().out) == {"schema": "poa.request/v1"}


def test_dispatch_serve_passes_connection_settings(monkeypatch) -> None:
    seen: dict = {}

    def _fake_serve(*, host: str, port: int, bus: object) -> None:
        seen["target"] = (host, port, bus)

    monkeypatch.setattr("subllm.cli_poa.serve", _fake_serve)
    bus = _FakeBus()
    assert dispatch(bus, _parser().parse_args(["serve", "--port", "9000"])) == 0
    assert seen["target"] == ("127.0.0.1", 9000, bus)


def test_dispatch_poa_query_forwards_filters(capsys) -> None:
    bus = _FakeBus(query_results={RESOLVE_ROUTE_URI: {"provider": "zai"}})
    args = _parser().parse_args(
        [
            "poa",
            "query",
            RESOLVE_ROUTE_URI,
            "--application",
            "app",
            "--function",
            "fn",
            "--provider",
            "zai",
            "--run-id",
            "r1",
        ]
    )
    assert dispatch(bus, args) == 0
    assert bus.queries[0] == {
        "schema": "subllm.query/v1",
        "process_uri": RESOLVE_ROUTE_URI,
        "application": "app",
        "function": "fn",
        "provider": "zai",
        "run_id": "r1",
    }
    assert json.loads(capsys.readouterr().out) == {"provider": "zai"}


def test_dispatch_poa_command_with_sources_builds_closed_command(capsys) -> None:
    bus = _FakeBus(command_results={IMPORT_CREDENTIALS_URI: {"result": {"imported": []}}})
    args = _parser().parse_args(
        [
            "poa",
            "command",
            IMPORT_CREDENTIALS_URI,
            "--process-ref",
            "subllm.import-credentials",
            "--application",
            "app",
            "--source",
            "a.env",
            "--source",
            "b.env",
            "--target",
            "t.env",
        ]
    )
    assert dispatch(bus, args) == 0
    command = bus.commands[0]
    assert command["schema"] == "subllm.command/v1"
    assert command["process_uri"] == IMPORT_CREDENTIALS_URI
    assert command["process_ref"] == "subllm.import-credentials"
    assert command["input_ref"] == ROUTE_INPUT
    assert command["sources"] == ["a.env", "b.env"]
    assert command["target"] == "t.env"
    assert command["idempotency_key"].startswith("cli.command.")
    assert isinstance(json.loads(capsys.readouterr().out), dict)


def test_dispatch_poa_command_defaults_target_when_sources_given() -> None:
    bus = _FakeBus()
    args = _parser().parse_args(["poa", "command", IMPORT_CREDENTIALS_URI, "--source", "a.env"])
    assert dispatch(bus, args) == 0
    command = bus.commands[0]
    assert command["sources"] == ["a.env"]
    assert command["target"] == ".env"


def test_dispatch_list_and_contract_use_policy_queries(capsys) -> None:
    routes = {LIST_ROUTES_URI: {"routes": [{"provider": "zai"}]}, EXPORT_CONTRACT_URI: {"profile": "v1"}}
    bus = _FakeBus(query_results=routes)
    assert dispatch(bus, _parser().parse_args(["list"])) == 0
    assert json.loads(capsys.readouterr().out) == [{"provider": "zai"}]
    contract_args = _parser().parse_args(["contract", "app", "fn"])
    assert dispatch(bus, contract_args) == 0
    assert bus.queries[-1] == {
        "schema": "subllm.query/v1",
        "process_uri": EXPORT_CONTRACT_URI,
        "application": "app",
        "function": "fn",
    }
    assert json.loads(capsys.readouterr().out) == {"profile": "v1"}


def test_dispatch_env_import_and_path_route_correctly() -> None:
    bus = _FakeBus(
        command_results={IMPORT_CREDENTIALS_URI: {"result": {"imported": ["ZAI_API_KEY"]}}},
        query_results={OBSERVE_CREDENTIALS_URI: {"path": "/tmp/x/.env", "credentials": {}}},
    )
    assert dispatch(bus, _parser().parse_args(["env", "import", "a.env"])) == 0
    assert bus.commands[0]["process_uri"] == IMPORT_CREDENTIALS_URI
    assert dispatch(bus, _parser().parse_args(["env", "path"])) == 0
    assert bus.queries[-1]["process_uri"] == OBSERVE_CREDENTIALS_URI


def test_main_returns_exit_code_2_on_domain_error(monkeypatch, capsys) -> None:
    class _FailingPolicyBus(_FakeBus):
        def query(self, document: dict) -> dict:
            raise SubLLMError("boom")

    monkeypatch.setattr("subllm.cli.PolicyBus", _FailingPolicyBus)
    assert main(["check"]) == 2
    assert capsys.readouterr().out == "subllm: boom\n"
