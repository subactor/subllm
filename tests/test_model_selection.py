"""Requested models stay within policy candidates and cannot silently fall back."""
from dataclasses import replace

import pytest

from subllm import CompletionError, client_routes, complete, resolve
from subllm.client_types import CompletionResponse, _RetryableAttemptError

MESSAGES = [{"role": "user", "content": "canary"}]


@pytest.fixture
def routes(monkeypatch):
    base = resolve("todo2code", "semantic", environ={"ZAI_API_KEY": "id.secret"})
    gemini = replace(base, provider="agy", model="gemini-3.8-flash",
                     wire_model="gemini-3.8-flash", litellm_model="gemini/gemini-3.8-flash",
                     transport="gemini-sdk", priority=10)
    candidates = [base, gemini]
    monkeypatch.setattr(client_routes, "available_routes", lambda *a, **kw: candidates)
    return candidates


@pytest.mark.parametrize("model", ["gemini-3.8-flash", "agy/gemini-3.8-flash",
                                  "gemini/gemini-3.8-flash"])
def test_explicit_model_selects_matching_policy_candidate(monkeypatch, routes, model):
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append(route)
        return CompletionResponse("ok", route.provider, route.wire_model)

    monkeypatch.setattr(client_routes, "_complete_route", invoke)
    result = complete("todo2code", "semantic", MESSAGES, model=model)
    assert result.provider == "agy" and result.model == "gemini-3.8-flash"
    assert calls == [routes[1]]


def test_selected_model_failure_never_calls_another_model(monkeypatch, routes):
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append(route.provider)
        raise _RetryableAttemptError("offline", outcome="provider_unavailable")

    monkeypatch.setattr(client_routes, "_complete_route", invoke)
    with pytest.raises(CompletionError):
        complete("todo2code", "semantic", MESSAGES, model="gemini-3.8-flash")
    assert calls == ["agy"]


def test_failover_can_use_another_allowed_provider_of_the_same_model(monkeypatch, routes):
    routes.append(replace(routes[1], provider="openrouter", priority=30))
    calls = []

    def invoke(route, *args, **kwargs):
        calls.append(route.provider)
        if route.provider == "agy":
            raise _RetryableAttemptError("offline", outcome="provider_unavailable")
        return CompletionResponse("ok", route.provider, route.wire_model)

    monkeypatch.setattr(client_routes, "_complete_route", invoke)
    result = complete("todo2code", "semantic", MESSAGES, model="gemini-3.8-flash")
    assert result.provider == "openrouter"
    assert calls == ["agy", "openrouter"]


@pytest.mark.parametrize("model", ["unregistered-model", "", True, 123])
def test_invalid_or_unconfigured_model_never_invokes_provider(monkeypatch, routes, model):
    monkeypatch.setattr(client_routes, "_complete_route", lambda *a, **kw: pytest.fail("provider invoked"))
    with pytest.raises(CompletionError):
        complete("todo2code", "semantic", MESSAGES, model=model)


@pytest.mark.parametrize("model", [None, "todo2code/semantic"])
def test_default_route_alias_preserves_existing_selection(monkeypatch, routes, model):
    monkeypatch.setattr(client_routes, "_complete_route", lambda route, *a, **kw:
                        CompletionResponse("ok", route.provider, route.wire_model))
    assert complete("todo2code", "semantic", MESSAGES, model=model).provider == "zai"


def test_explicit_model_cannot_bypass_adaptive_route(monkeypatch, routes):
    from subllm import adaptive
    monkeypatch.setattr(adaptive, "execute", lambda *a, **kw: pytest.fail("adaptive execution"))
    monkeypatch.setattr(adaptive, "policy", lambda _: {"routes": {"todo2code/semantic": {"model": "other"}}})
    with pytest.raises(CompletionError, match="adaptive route"):
        complete("todo2code", "semantic", MESSAGES, model="gemini-3.8-flash")
