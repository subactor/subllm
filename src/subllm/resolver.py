from __future__ import annotations

import os
from collections.abc import Mapping

from .policy import APPLICATIONS, MODELS, PROVIDERS, ROUTES
from .types import ConfiguredRoute, ResolvedRoute, RouteCandidate, RoutePolicy


class SubLLMError(RuntimeError):
    """Base error for deterministic policy or credential resolution failures."""


class UnknownRouteError(SubLLMError):
    pass


class InvalidPolicyError(SubLLMError):
    pass


class MissingCredentialError(SubLLMError):
    pass


_PLACEHOLDER_PARTS = (
    "ADD_SIGNATURE_SECRET",
    "SIGNATURE_SECRET",
    "CHANGEME",
    "PLACEHOLDER",
    "<",
    ">",
)


def _credential_is_valid(provider: str, value: str | None) -> bool:
    candidate = (value or "").strip()
    if not candidate or any(part in candidate.upper() for part in _PLACEHOLDER_PARTS):
        return False
    if provider == "zai":
        if candidate.count(".") != 1:
            return False
        key_id, secret = candidate.split(".", 1)
        return bool(key_id and secret)
    return True


def route_policy(application: str, function: str) -> RoutePolicy:
    try:
        return ROUTES[(application, function)]
    except KeyError as exc:
        raise UnknownRouteError(f"unknown SubLLM route: {application}/{function}") from exc


def _configured(application: str, function: str, candidate: RouteCandidate) -> ConfiguredRoute:
    app = APPLICATIONS[application]
    provider = PROVIDERS[candidate.provider]
    model = MODELS[candidate.model]
    if model.forbidden:
        raise InvalidPolicyError(f"forbidden model in route: {model.id}")
    try:
        provider_model = model.providers[provider.id]
    except KeyError as exc:
        raise InvalidPolicyError(f"model {model.id} is unavailable through provider {provider.id}") from exc
    headers: dict[str, str] = {}
    if provider.attribution_headers:
        headers = {"HTTP-Referer": app.url, "X-OpenRouter-Title": app.title}
    return ConfiguredRoute(
        application=application,
        function=function,
        provider=provider.id,
        model=model.id,
        priority=candidate.priority,
        api_base=provider.api_base,
        api_key_env=provider.api_key_env,
        litellm_model=provider_model.litellm_model,
        wire_model=provider_model.wire_model,
        extra_headers=headers,
    )


def configured_routes(application: str, function: str) -> tuple[ConfiguredRoute, ...]:
    policy = route_policy(application, function)
    ordered = sorted(policy.candidates, key=lambda item: item.priority)
    return tuple(_configured(application, function, item) for item in ordered)


def configured_route(application: str, function: str, *, provider: str | None = None) -> ConfiguredRoute:
    routes = configured_routes(application, function)
    for route in routes:
        if provider is None or route.provider == provider:
            return route
    raise UnknownRouteError(f"route {application}/{function} does not allow provider {provider}")


def available_routes(
    application: str,
    function: str,
    *,
    environ: Mapping[str, str] | None = None,
    credentials: Mapping[str, str] | None = None,
) -> tuple[ResolvedRoute, ...]:
    environment = os.environ if environ is None else environ
    explicit = credentials or {}
    resolved: list[ResolvedRoute] = []
    for route in configured_routes(application, function):
        api_key = explicit.get(route.provider, environment.get(route.api_key_env, ""))
        if not _credential_is_valid(route.provider, api_key):
            continue
        resolved.append(
            ResolvedRoute(
                **route.public_dict(),
                api_key=api_key,
            )
        )
    return tuple(resolved)


def resolve(
    application: str,
    function: str,
    *,
    provider: str | None = None,
    environ: Mapping[str, str] | None = None,
    credentials: Mapping[str, str] | None = None,
) -> ResolvedRoute:
    for route in available_routes(application, function, environ=environ, credentials=credentials):
        if provider is None or route.provider == provider:
            return route
    configured = configured_routes(application, function)
    if provider is not None and not any(route.provider == provider for route in configured):
        raise UnknownRouteError(f"route {application}/{function} does not allow provider {provider}")
    required = sorted({route.api_key_env for route in configured if provider is None or route.provider == provider})
    raise MissingCredentialError(
        f"no valid credential for {application}/{function}; configure one of: {', '.join(required)}"
    )


def validate_policy() -> None:
    for key, route in ROUTES.items():
        if key != (route.application, route.function):
            raise InvalidPolicyError(f"route key mismatch: {key}")
        if route.application not in APPLICATIONS:
            raise InvalidPolicyError(f"unknown application in route: {route.application}")
        priorities = [candidate.priority for candidate in route.candidates]
        if len(priorities) != len(set(priorities)):
            raise InvalidPolicyError(f"duplicate priority in route: {route.application}/{route.function}")
        for candidate in route.candidates:
            if candidate.provider not in PROVIDERS:
                raise InvalidPolicyError(f"unknown provider in route: {candidate.provider}")
            if candidate.model not in MODELS:
                raise InvalidPolicyError(f"unknown model in route: {candidate.model}")
            model = MODELS[candidate.model]
            if model.forbidden:
                raise InvalidPolicyError(f"forbidden model in route: {candidate.model}")
            if candidate.provider not in model.providers:
                raise InvalidPolicyError(
                    f"model {candidate.model} is unavailable through provider {candidate.provider}"
                )

