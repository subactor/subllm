from __future__ import annotations

from pathlib import Path

import pytest

from subllm import (
    InvalidPolicyError,
    configured_routes,
    find_policy_file,
    load_policy_config,
    resolve,
)


def _policy_file(
    path: Path,
    *,
    cursor_enabled: bool = True,
    cursor_priority: int = 0,
    cursor_model: str = "gpt-5.6-sol",
    zai_enabled: bool = True,
    zai_priority: int = 10,
    zai_model: str = "glm-5.2",
    openrouter_enabled: bool = True,
    openrouter_priority: int = 20,
    openrouter_model: str = "glm-5.2",
) -> Path:
    path.write_text(
        "\n".join(
            (
                "schema_version = 2",
                "",
                "[providers.cursor]",
                f"enabled = {str(cursor_enabled).lower()}",
                f"priority = {cursor_priority}",
                f'default_model = "{cursor_model}"',
                "",
                "[providers.zai]",
                f"enabled = {str(zai_enabled).lower()}",
                f"priority = {zai_priority}",
                f'default_model = "{zai_model}"',
                "",
                "[providers.openrouter]",
                f"enabled = {str(openrouter_enabled).lower()}",
                f"priority = {openrouter_priority}",
                f'default_model = "{openrouter_model}"',
                "",
                '[applications.doctor-agent]',
                'name = "doctor-agent"',
                'url = "https://github.com/subactor/doctor-agent"',
                "",
                '[applications.repair-agent]',
                'name = "repair-agent"',
                'url = "https://github.com/subactor/repair-agent"',
                "",
                '[applications.validator-agent]',
                'name = "validator-agent"',
                'url = "https://github.com/subactor/validator-agent"',
                "",
                '[applications.skills-agent]',
                'name = "skills-agent"',
                'url = "https://github.com/subactor/skills-agent"',
                "",
                '[applications.onedev-agent]',
                'name = "onedev-agent"',
                'url = "https://github.com/subactor/onedev-agent"',
                "",
                '[applications.todo2code]',
                'name = "todo2code"',
                'url = "https://github.com/semcod/todo2code"',
                "",
                '[applications.koru-agent]',
                'name = "Koru"',
                'url = "https://github.com/semcod/koru"',
                "",
                '[applications.platform]',
                'name = "Subactor Platform"',
                'url = "https://github.com/subactor/platform"',
                "",
                '[applications.szeptnik-one]',
                'name = "Szeptnik One"',
                'url = "https://github.com/tom-sapletta-com/watch"',
                "",
                '[applications.supervisor]',
                'name = "Subactor Supervisor"',
                'url = "https://github.com/subactor/supervisor"',
                "",
            )
        ),
        encoding="utf-8",
    )
    return path


def test_repository_policy_file_is_discovered() -> None:
    path = find_policy_file(cwd=Path(__file__).resolve().parents[1])
    assert path is not None
    assert path.name == "subllm.toml"
    policy = load_policy_config(cwd=path.parent)
    assert policy.providers["cursor"].priority == 0
    assert policy.providers["zai"].priority == 10
    assert policy.providers["openrouter"].default_model == "glm-5.2"
    assert policy.applications["platform"].name == "Subactor Platform"
    assert policy.applications["szeptnik-one"].name == "Szeptnik One"


def test_priority_can_be_reversed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _policy_file(
        tmp_path / "subllm.toml",
        cursor_enabled=False,
        zai_priority=20,
        openrouter_priority=10,
    )
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy))

    route = resolve(
        "doctor-agent",
        "repair-proposal",
        environ={"ZAI_API_KEY": "id.signature", "OPENROUTER_API_KEY": "or-key"},
    )
    assert route.provider == "openrouter"
    assert route.priority == 10


def test_provider_can_be_disabled_and_default_model_changed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy_file(
        tmp_path / "subllm.toml",
        cursor_enabled=False,
        zai_enabled=False,
        openrouter_model="grok-4.5",
    )
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy))

    route = resolve(
        "repair-agent",
        "repair-plan",
        environ={"ZAI_API_KEY": "id.signature", "OPENROUTER_API_KEY": "or-key"},
    )
    assert route.provider == "openrouter"
    assert route.model == "grok-4.5"
    assert route.litellm_model == "openrouter/x-ai/grok-4.5"


def test_default_model_deduplicates_the_same_explicit_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy_file(tmp_path / "subllm.toml", openrouter_model="deepseek-v4-pro")
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy))

    routes = configured_routes("repair-agent", "repair-plan")
    assert [(route.provider, route.model) for route in routes].count(
        ("openrouter", "deepseek-v4-pro")
    ) == 1


def test_all_providers_disabled_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    policy = _policy_file(
        tmp_path / "subllm.toml",
        cursor_enabled=False,
        zai_enabled=False,
        openrouter_enabled=False,
    )
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy))

    with pytest.raises(InvalidPolicyError, match="no enabled candidate"):
        configured_routes("doctor-agent", "repair-proposal")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    (
        ({"openrouter_model": "gemini-3.1-pro-preview"}, "forbidden default model"),
        ({"zai_model": "grok-4.5"}, "unavailable through provider zai"),
        ({"cursor_model": "glm-5.2"}, "unavailable through provider cursor"),
        ({"zai_priority": 20, "openrouter_priority": 20}, "unique priorities"),
    ),
)
def test_invalid_provider_configuration_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kwargs: dict[str, object],
    message: str,
) -> None:
    policy = _policy_file(tmp_path / "subllm.toml", **kwargs)
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy))

    with pytest.raises(InvalidPolicyError, match=message):
        load_policy_config()


def test_application_name_and_url_control_openrouter_attribution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy_file(tmp_path / "subllm.toml")
    text = policy.read_text(encoding="utf-8").replace(
        'name = "doctor-agent"\nurl = "https://github.com/subactor/doctor-agent"',
        'name = "Subactor Doctor"\nurl = "https://subactor.com/doctor"',
    )
    policy.write_text(text, encoding="utf-8")
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy))

    route = next(
        item for item in configured_routes("doctor-agent", "repair-proposal") if item.provider == "openrouter"
    )
    assert route.application == "doctor-agent"
    assert route.application_name == "Subactor Doctor"
    assert route.extra_headers == {
        "HTTP-Referer": "https://subactor.com/doctor",
        "X-OpenRouter-Title": "Subactor Doctor",
    }


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        ('name = "doctor-agent"', 'name = ""', "name must be"),
        (
            'url = "https://github.com/subactor/doctor-agent"',
            'url = "http://localhost/doctor"',
            "public HTTPS URL",
        ),
    ),
)
def test_invalid_application_identity_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    old: str,
    new: str,
    message: str,
) -> None:
    policy = _policy_file(tmp_path / "subllm.toml")
    policy.write_text(policy.read_text(encoding="utf-8").replace(old, new, 1), encoding="utf-8")
    monkeypatch.setenv("SUBLLM_POLICY_FILE", str(policy))

    with pytest.raises(InvalidPolicyError, match=message):
        load_policy_config()
