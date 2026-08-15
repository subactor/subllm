from __future__ import annotations

import os
from collections.abc import Mapping

from .credential_env import credential_is_valid, merged_environment
from .errors import (
    InvalidPolicyError,
    MissingCredentialError,
    UnknownRouteError,
)
from .policy import APPLICATIONS, MODELS, PROVIDERS, ROUTES
from .policy_config import RuntimePolicyConfig, load_policy_config
from .provider_order import routing_provider_order
from .types import ConfiguredRoute, ResolvedRoute, RouteCandidate, RoutePolicy


def route_policy(application: str, function: str) -> RoutePolicy:
    try:
        return ROUTES[(application, function)]
    except KeyError as exc:
        raise UnknownRouteError(f"unknown SubLLM route: {application}/{function}") from exc


def _configured(
    application: str,
    function: str,
    candidate: RouteCandidate,
    runtime_policy: RuntimePolicyConfig,
    *,
    order: tuple[str, ...] | None,
) -> ConfiguredRoute:
    app = runtime_policy.applications[application]
    provider = PROVIDERS[candidate.provider]
    provider_policy = runtime_policy.providers[provider.id]
    model_id = candidate.model or provider_policy.default_model
    model = MODELS[model_id]
    if model.forbidden:
        raise InvalidPolicyError(f"forbidden model in route: {model.id}")
    try:
        provider_model = model.providers[provider.id]
    except KeyError as exc:
        raise InvalidPolicyError(f"model {model.id} is unavailable through provider {provider.id}") from exc
    headers: dict[str, str] = {}
    if provider.attribution_headers:
        headers = {"HTTP-Referer": app.url, "X-OpenRouter-Title": app.name}
    if order is None:
        priority = provider_policy.priority + candidate.priority_offset
    else:
        priority = order.index(provider.id) * 10 + candidate.priority_offset
    return ConfiguredRoute(
        application=application,
        application_name=app.name,
        application_url=app.url,
        function=function,
        provider=provider.id,
        model=model.id,
        priority=priority,
        api_base=provider.api_base,
        api_key_env=provider.api_key_env,
        litellm_model=provider_model.litellm_model,
        wire_model=provider_model.wire_model,
        extra_headers=headers,
    )


def configured_routes(
    application: str,
    function: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> tuple[ConfiguredRoute, ...]:
    policy = route_policy(application, function)
    runtime_policy = load_policy_config()
    order_environ = environ if environ is not None else os.environ
    order = routing_provider_order(environ=order_environ)
    candidates = (
        _configured(application, function, item, runtime_policy, order=order)
        for item in policy.candidates
        if runtime_policy.providers[item.provider].enabled and (order is None or item.provider in order)
    )
    ordered = sorted(candidates, key=lambda item: item.priority)
    if not ordered:
        raise InvalidPolicyError(f"no enabled candidate for route: {application}/{function}")
    priorities = [route.priority for route in ordered]
    if len(priorities) != len(set(priorities)):
        raise InvalidPolicyError(f"duplicate effective priority in route: {application}/{function}")
    unique: list[ConfiguredRoute] = []
    seen: set[tuple[str, str]] = set()
    for route in ordered:
        key = (route.provider, route.model)
        if key not in seen:
            unique.append(route)
            seen.add(key)
    return tuple(unique)


def configured_route(
    application: str,
    function: str,
    *,
    provider: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> ConfiguredRoute:
    routes = configured_routes(application, function, environ=environ)
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
    environment = merged_environment(environ=environ)
    explicit = credentials or {}
    resolved: list[ResolvedRoute] = []
    for route in configured_routes(application, function, environ=environment):
        api_key = explicit.get(route.provider, environment.get(route.api_key_env, ""))
        if not credential_is_valid(route.provider, api_key):
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
    environment = merged_environment(environ=environ)
    for route in available_routes(application, function, environ=environment, credentials=credentials):
        if provider is None or route.provider == provider:
            return route
    configured = configured_routes(application, function, environ=environment)
    if provider is not None and not any(route.provider == provider for route in configured):
        raise UnknownRouteError(f"route {application}/{function} does not allow provider {provider}")
    required = sorted({route.api_key_env for route in configured if provider is None or route.provider == provider})
    raise MissingCredentialError(
        f"no valid credential for {application}/{function}; configure one of: {', '.join(required)}"
    )


def validate_policy() -> None:
    runtime_policy = load_policy_config()
    for key, route in ROUTES.items():
        if key != (route.application, route.function):
            raise InvalidPolicyError(f"route key mismatch: {key}")
        if route.application not in APPLICATIONS:
            raise InvalidPolicyError(f"unknown application in route: {route.application}")
        for candidate in route.candidates:
            if candidate.provider not in PROVIDERS:
                raise InvalidPolicyError(f"unknown provider in route: {candidate.provider}")
            if candidate.priority_offset < 0:
                raise InvalidPolicyError(f"negative priority offset in route: {route.application}/{route.function}")
            model_id = candidate.model or runtime_policy.providers[candidate.provider].default_model
            if model_id not in MODELS:
                raise InvalidPolicyError(f"unknown model in route: {candidate.model}")
            model = MODELS[model_id]
            if model.forbidden:
                raise InvalidPolicyError(f"forbidden model in route: {model_id}")
            if candidate.provider not in model.providers:
                raise InvalidPolicyError(
                    f"model {model_id} is unavailable through provider {candidate.provider}"
                )
        configured_routes(route.application, route.function)
