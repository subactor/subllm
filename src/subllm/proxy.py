from __future__ import annotations

import datetime
import json
import math
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
from pathlib import Path
from threading import Lock
from typing import Any
from urllib import request as urllib_request
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from . import adaptive
from .cli_common import CLI_EXECUTABLES
from .client_routes import _complete_route, complete
from .client_types import CompletionResponse, _RetryableAttemptError
from .credential_env import credential_is_valid, merged_environment
from .errors import QUALITY_VALIDATOR_ERROR_CODE, CompletionError, InvalidResponseContractError, SubLLMError
from .health import order_with_last_resort, record_failure, record_success
from .openrouter_routing import apply_parameters
from .policy import MODELS, PROVIDERS, ROUTES
from .policy_config import load_policy_config, resolve_attempt_timeout
from .provider_order import routing_provider_order
from .proxy_decide import SYSTEM_ONE_REQUEST_SCHEMA as SYSTEM_ONE_REQUEST_SCHEMA
from .proxy_decide import SYSTEM_ONE_RESPONSE_SCHEMA as SYSTEM_ONE_RESPONSE_SCHEMA
from .proxy_decide import _build_ollama_d1_questions as _build_ollama_d1_questions
from .proxy_decide import _build_system_one_messages as _build_system_one_messages
from .proxy_decide import _extract_json_object as _extract_json_object
from .proxy_decide import _finite_probability as _finite_probability
from .proxy_decide import _model_family as _model_family
from .proxy_decide import _normalize_ollama_d1_response as _normalize_ollama_d1_response
from .proxy_decide import _normalize_question_options as _normalize_question_options
from .proxy_decide import _normalize_system_one_probabilities as _normalize_system_one_probabilities
from .proxy_forward import FORWARD_USAGE_PATHS as FORWARD_USAGE_PATHS
from .proxy_forward import UPSTREAM_FORWARD_TIMEOUT_BOUNDS as UPSTREAM_FORWARD_TIMEOUT_BOUNDS
from .proxy_forward import UPSTREAM_FORWARD_TIMEOUT_DEFAULT as UPSTREAM_FORWARD_TIMEOUT_DEFAULT
from .proxy_forward import forward_usage_counts as forward_usage_counts
from .proxy_forward import upstream_forward_timeout as upstream_forward_timeout
from .proxy_security import PROXY_ALLOWED_ORIGINS_ENV as PROXY_ALLOWED_ORIGINS_ENV
from .proxy_security import PROXY_BEARER_ENV as PROXY_BEARER_ENV
from .proxy_security import ProxyUnauthorizedError as ProxyUnauthorizedError
from .proxy_security import proxy_origin_allowed as proxy_origin_allowed
from .proxy_security import require_route_bearer as require_route_bearer
from .quality_schema import declared_schema_gate
from .stream_transport import ACTIVE_STREAM, stream_error, supported_routes
from .types import ResolvedRoute
from .usage import record_attempt

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
DEFAULT_OLLAMA_UPSTREAM = "http://127.0.0.1:11434"


DEFAULT_PROXY_PORT = 11435


_CATALOG_READER_LOCK = Lock()
SYSTEM_ONE_LOCAL_OLLAMA_MODELS: tuple[str, ...] = (
    "qwen3.5:0.8b",
    "willman-eval:qwen3.5-0.8b",
    "qwen3.5:2b",
    "willman-eval:qwen3.5-2b",
    "qwen3.5:4b",
    "willman-eval:qwen3.5-4b",
    "qwen2.5:1.5b",
)
SYSTEM_ONE_DEFAULT_D1_MODEL = "d1:3b"

_TICKET_PATTERN = re.compile(r"^(ticket-[A-Za-z0-9_.-]+)")


def _package_version() -> str:
    try:
        return metadata.version("subactor-subllm")
    except metadata.PackageNotFoundError:
        return "unknown"


def _resolve_system_one_ollama_upstream(configured_upstream: str) -> str:
    """Resolve an active local Ollama upstream for System One, falling back to DEFAULT_OLLAMA_UPSTREAM."""
    if is_upstream_ollama_alive(configured_upstream):
        return configured_upstream
    if configured_upstream != DEFAULT_OLLAMA_UPSTREAM and is_upstream_ollama_alive(DEFAULT_OLLAMA_UPSTREAM):
        return DEFAULT_OLLAMA_UPSTREAM
    return configured_upstream


_SIZE_PREFERENCES: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("0.8b", "0.6b", "0.5b", "322m", "340m", "270m", "laya", "nanojev", "jevlike"),
     ("qwen3.5:0.8b", "willman-eval:qwen3.5-0.8b", "qwen2.5:1.5b")),
    (("2b",), ("qwen3.5:2b", "willman-eval:qwen3.5-2b", "qwen3.5:0.8b")),
    (("4b", "kev", "semif", "jevos"), ("qwen3.5:4b", "willman-eval:qwen3.5-4b", "qwen3.5:0.8b")),
)


def _is_d1(name: str) -> bool:
    n = name.strip().lower()
    return n == "d1" or n.startswith("d1:")


def _installed_ollama_model_names(upstream_url: str) -> list[str]:
    names = (str(m.get("name") or m.get("model") or "").strip() for m in get_upstream_ollama_models(upstream_url) or [])
    return [name for name in names if name]


def _first_installed(candidates: Sequence[str], installed: set[str]) -> str | None:
    return next((candidate for candidate in candidates if candidate in installed), None)


def _exact_installed_model(req: str, installed: set[str], exclude_d1: bool) -> str | None:
    """The requested tag itself, or its ``:latest`` form (never for the bare ``d1`` alias)."""
    if req in installed and not (exclude_d1 and _is_d1(req)):
        return req
    latest = f"{req}:latest"
    if latest in installed and not (exclude_d1 and _is_d1(latest)) and req.lower() != "d1":
        return latest
    return None


def _size_preferred_candidates(req_low: str) -> tuple[str, ...]:
    for needles, candidates in _SIZE_PREFERENCES:
        if any(needle in req_low for needle in needles):
            return candidates
    return ()


def _select_local_system_one_ollama_model(
    requested_model: str,
    upstream_url: str = DEFAULT_OLLAMA_UPSTREAM,
    *,
    exclude_d1: bool = False,
) -> str | None:
    """Select an installed local System One model, preferring d1 when it was requested."""
    installed_names = _installed_ollama_model_names(upstream_url)
    if not installed_names:
        return None
    installed_set = set(installed_names)
    req = requested_model.strip()
    exact = _exact_installed_model(req, installed_set, exclude_d1)
    if exact is not None:
        return exact
    if not exclude_d1 and _is_d1(req):
        d1_candidate = SYSTEM_ONE_DEFAULT_D1_MODEL if req.lower() == "d1" else req
        if d1_candidate in installed_set:
            return d1_candidate
        # If the requested d1 tag is unavailable, keep the pre-existing local
        # small-Qwen fallback before routing to the configured SubLLM provider.
        return _first_installed(SYSTEM_ONE_LOCAL_OLLAMA_MODELS, installed_set)
    if exclude_d1:
        return _first_installed(SYSTEM_ONE_LOCAL_OLLAMA_MODELS, installed_set)
    preferred = [*_size_preferred_candidates(req.lower()), *SYSTEM_ONE_LOCAL_OLLAMA_MODELS]
    return _first_installed(preferred, installed_set) or installed_names[0]


_NATIVE_D1_NAMES = ("d1", "d1-ultra", "liquid-d1-ultra")
_NATIVE_D1_PREFIXES = ("d1:", "d1-", "liquid-", "liquid/")


def _is_native_d1_model(model: str) -> bool:
    n = model.strip().lower()
    return n in _NATIVE_D1_NAMES or n.startswith(_NATIVE_D1_PREFIXES)


def _ollama_system_one_body(ollama_model: str, messages: Sequence[Mapping[str, Any]], temperature: float,
                            request_payload: Mapping[str, Any] | None) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": ollama_model,
        "messages": [dict(m) for m in messages],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {"temperature": max(0.0, float(temperature)), "num_predict": 256},
    }
    if request_payload is not None and request_payload.get("keep_alive") is not None:
        from .decisions import parse_keep_alive

        body["keep_alive"] = parse_keep_alive(request_payload.get("keep_alive"))
    return body


def _ollama_system_one_response(data: Any, ollama_model: str) -> CompletionResponse:
    is_map = isinstance(data, Mapping)
    msg = data.get("message") if is_map else {}
    content = str(msg.get("content") or "") if isinstance(msg, Mapping) else ""
    prompt_tokens = int(data.get("prompt_eval_count") or 0) if is_map else 0
    eval_tokens = int(data.get("eval_count") or 0) if is_map else 0
    return CompletionResponse(
        content=content,
        provider="ollama",
        model=str(data.get("model") or ollama_model),
        usage={"input_tokens": prompt_tokens, "output_tokens": eval_tokens},
        finish_reason=str(data.get("done_reason") or "stop"),
    )


def _complete_ollama_system_one(
    upstream_url: str,
    ollama_model: str,
    messages: Sequence[Mapping[str, Any]],
    *,
    temperature: float = 0.2,
    timeout_seconds: float = 6.0,
    request_payload: Mapping[str, Any] | None = None,
    application: str = "subllm",
    function: str = "decision-routing",
    request_id: str | None = None,
) -> CompletionResponse:
    """Invoke local Ollama `/api/chat` with `think: false` and `format: json` for fast System One scoring."""
    if _is_native_d1_model(ollama_model):
        if request_payload is None:
            raise ValueError("native d1 System One requests require the typed request payload")
        return _complete_ollama_d1_system_one(
            upstream_url,
            ollama_model,
            request_payload,
            timeout_seconds=timeout_seconds,
            application=application,
            function=function,
            request_id=request_id,
        )
    body = _ollama_system_one_body(ollama_model, messages, temperature, request_payload)
    req = Request(
        f"{upstream_url.rstrip('/')}/api/chat",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "subllm-proxy"},
        method="POST",
    )
    with urlopen(req, timeout=timeout_seconds) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return _ollama_system_one_response(data, ollama_model)


def _complete_ollama_d1_system_one(
    upstream_url: str,
    ollama_model: str,
    payload: Mapping[str, Any],
    *,
    timeout_seconds: float = 6.0,
    application: str = "subllm",
    function: str = "decision-routing",
    request_id: str | None = None,
) -> CompletionResponse:
    """Reuse the shared local-only SDK, including native capture and usage."""
    from .decisions import decide_legacy

    native_payload = dict(payload, model=ollama_model)
    if native_payload.get("state") is None:
        native_payload["state"] = {"messages": _build_system_one_messages(payload)}
    from .decisions import parse_keep_alive

    keep_alive = (
        {"keep_alive": parse_keep_alive(payload["keep_alive"])}
        if payload.get("keep_alive") is not None
        else {}
    )
    parsed = decide_legacy(native_payload, base_url=upstream_url, timeout_seconds=timeout_seconds,
                           application=application, function=function, request_id=request_id, **keep_alive)
    return CompletionResponse(
        content=json.dumps(parsed, ensure_ascii=False),
        provider="ollama",
        model=parsed["model"],
        usage=parsed["usage"],
    )


UPSTREAM_LIVENESS_TTL_ENV = "SUBLLM_UPSTREAM_LIVENESS_TTL"
UPSTREAM_LIVENESS_TTL_DEFAULT = 2.0
_LIVENESS: dict[str, tuple[float, str]] = {}
_LIVENESS_LOCKS: dict[str, threading.Lock] = {}
_LIVENESS_GUARD = threading.Lock()


def _liveness_ttl() -> float:
    try:
        ttl = float(os.environ.get(UPSTREAM_LIVENESS_TTL_ENV, UPSTREAM_LIVENESS_TTL_DEFAULT))
    except ValueError:
        return UPSTREAM_LIVENESS_TTL_DEFAULT
    return ttl if math.isfinite(ttl) and 0 <= ttl <= 60 else UPSTREAM_LIVENESS_TTL_DEFAULT


def _probe_upstream_state(upstream_url: str, timeout: float) -> str:
    try:
        req = Request(f"{upstream_url.rstrip('/')}/api/tags", headers={"User-Agent": "subllm-proxy"})
        with urlopen(req, timeout=timeout) as resp:
            return "alive" if resp.status == 200 else "dead"
    except TimeoutError:
        return "busy"
    except URLError as exc:
        return "busy" if isinstance(exc.reason, TimeoutError) else "dead"
    except Exception:
        return "dead"


def upstream_ollama_state(upstream_url: str = DEFAULT_OLLAMA_UPSTREAM, timeout: float = 0.5, *,
                          fresh: bool = False) -> str:
    """Shared Ollama liveness: ``alive``, ``busy`` (probe timed out) or ``dead`` (SUB-07).

    One probe per upstream per TTL (``SUBLLM_UPSTREAM_LIVENESS_TTL``, default 2 s); concurrent
    callers wait for the probe in flight instead of starting their own. ``fresh`` (health) always
    probes and refreshes the shared state.
    """
    key = upstream_url.rstrip("/")
    ttl = _liveness_ttl()
    cached = None if fresh else _LIVENESS.get(key)
    if cached is not None and cached[0] > time.monotonic():
        return cached[1]
    with _LIVENESS_GUARD:
        lock = _LIVENESS_LOCKS.setdefault(key, threading.Lock())
    with lock:
        cached = None if fresh else _LIVENESS.get(key)
        if cached is not None and cached[0] > time.monotonic():
            return cached[1]
        state = _probe_upstream_state(key, timeout)
        _LIVENESS[key] = (time.monotonic() + ttl, state)
        return state


def is_upstream_ollama_alive(upstream_url: str = DEFAULT_OLLAMA_UPSTREAM, timeout: float = 0.5, *,
                             fresh: bool = False) -> bool:
    """A busy Ollama (slow probe) is still local: forward to it instead of a cloud route (SUB-07)."""
    return upstream_ollama_state(upstream_url, timeout, fresh=fresh) != "dead"


@lru_cache(maxsize=2)
def _catalog_reader(path: str, ttl: float) -> tuple[Any, Any]:
    from procache.http import CachedHTTPReads, HTTPResponse

    return CachedHTTPReads.shared(path=path, ttl=ttl), HTTPResponse


def _optional_catalog_reader() -> tuple[Any, Any] | None:
    try:
        ttl = float(os.environ.get("SUBLLM_MODEL_CATALOG_CACHE_TTL", "15"))
        if not math.isfinite(ttl) or not 0 < ttl <= 3600:
            return None
        default = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "subactor/provider-http.sqlite3"
        path = os.environ.get("SUBACTOR_PROCACHE_PATH") or str(default)
        # lru_cache permits concurrent construction on an initial miss. Keep
        # SQLite initialization single-flight within this process as well.
        with _CATALOG_READER_LOCK:
            return _catalog_reader(path, ttl)
    except (ImportError, OSError, ValueError, sqlite3.Error):
        return None


def _anonymous_catalog_transport(url: str) -> bool:
    opener = getattr(urllib_request, "_opener", None)
    if opener is None:
        return True
    # An installed opener can add credentials/cookies outside Request.headers.
    # Only the standard anonymous handlers and default headers are known here.
    if any(name.lower() != "user-agent" for name, _ in getattr(opener, "addheaders", ())):
        return False
    standard = {"ProxyHandler", "UnknownHandler", "HTTPHandler", "HTTPDefaultErrorHandler",
                "HTTPRedirectHandler", "FTPHandler", "FileHandler", "DataHandler",
                "HTTPSHandler", "HTTPErrorProcessor"}
    for handler in getattr(opener, "handlers", ()):
        if type(handler).__module__ != "urllib.request" or type(handler).__name__ not in standard:
            return False
        # A TLS context can contain a client certificate whose identity is
        # unavailable here. HTTPS handlers do not affect plain HTTP requests.
        if urlparse(url).scheme == "https" and getattr(handler, "_context", None) is not None:
            return False
        if any(urlparse(url).username is not None for url in getattr(handler, "proxies", {}).values()):
            return False
    return True


def get_upstream_ollama_models(
    upstream_url: str = DEFAULT_OLLAMA_UPSTREAM, timeout: float = 0.8, *, fresh: bool = False,
) -> list[dict[str, Any]]:
    """Read a validated catalog; install ``.[cache]`` to share repeated reads.

    Health always uses its separate live transport. A zero/invalid
    SUBLLM_MODEL_CATALOG_CACHE_TTL or explicit freshness preserves live reads.
    """
    attempted = False
    models: list[dict[str, Any]] | None = None
    url = f"{upstream_url.rstrip('/')}/api/tags"
    headers = {"User-Agent": "subllm-proxy"}

    def decode(body: bytes) -> list[dict[str, Any]]:
        data = json.loads(body.decode("utf-8"))
        if (not isinstance(data, dict) or not isinstance(data.get("models"), list)
                or any(not isinstance(item, dict) for item in data["models"])):
            raise ValueError("Invalid Ollama model catalog")
        return data["models"]

    def read() -> tuple[int, dict[str, str], bytes]:
        nonlocal attempted, models
        attempted = True
        with urlopen(Request(url, headers=headers), timeout=timeout) as resp:
            body = resp.read()
            models = decode(body)
            return resp.status, dict(resp.headers), body

    try:
        # This transport sends no authentication headers. URL credentials are
        # not a known anonymous identity and retain the original live path.
        reader = (None if fresh or urlparse(upstream_url).username is not None
                  or not _anonymous_catalog_transport(upstream_url)
                  else _optional_catalog_reader())
        if reader is None:
            read()
            return models or []
        cache, response_type = reader

        def load():
            try:
                return response_type(*read())
            except HTTPError as error:
                # Give the canonical adapter the real 429 and Retry-After so
                # subsequent catalog callers honor the shared cooldown.
                with error:
                    return response_type(error.code, dict(error.headers or {}), error.read())

        try:
            response = cache.request("GET", url, load,
                                     scope=cache.credential_scope("anonymous"), headers=headers, cacheable=True)
        except (OSError, ValueError, sqlite3.Error):
            # A cache write can fail after a successful provider read. Reuse
            # that response; never issue a second upstream request.
            if not attempted:
                read()
            return models or []
        return decode(response.body) if 200 <= response.status < 300 else []
    except Exception:
        return []


def _catalog_model_entry(model_id: str, family: str, source: str, vision: bool) -> dict[str, Any]:
    return {
        "id": model_id,
        "name": f"{model_id}:latest",
        "model": f"{model_id}:latest",
        "family": family,
        "families": [family],
        "parameter_size": "unknown",
        "source": source,
        "vision": vision,
    }


def _upstream_model_entry(m: Mapping[str, Any], name: str) -> dict[str, Any]:
    details = m.get("details") if isinstance(m.get("details"), dict) else {}
    family = details.get("family") or _model_family(name)
    return {
        "id": name,
        "name": name,
        "model": name,
        "family": family,
        "families": details.get("families", [family]),
        "parameter_size": details.get("parameter_size", "unknown"),
        "source": "ollama-upstream",
        "vision": False,
        "details": details,
        "size": m.get("size") if type(m.get("size")) is int else 0,
        "digest": m.get("digest") if isinstance(m.get("digest"), str) else None,
        "modified_at": m.get("modified_at") if isinstance(m.get("modified_at"), str) else None,
    }


def list_proxy_models(
    upstream_url: str = DEFAULT_OLLAMA_UPSTREAM, include_upstream: bool = True, *, fresh: bool = False,
) -> list[dict[str, Any]]:
    """Return unified list of available models for OpenAI and Ollama formats."""
    models = [_catalog_model_entry(model_id, _model_family(model_id), "subllm", spec.vision)
              for model_id, spec in MODELS.items() if not spec.forbidden]
    seen_ids = {entry["id"] for entry in models}
    # Add registered route aliases
    for (app, func) in ROUTES:
        alias = f"{app}/{func}"
        if alias not in seen_ids:
            seen_ids.add(alias)
            models.append(_catalog_model_entry(alias, "custom", "subllm-route", False))
    if not include_upstream:
        return models
    upstream_models = (get_upstream_ollama_models(upstream_url, fresh=True) if fresh
                       else get_upstream_ollama_models(upstream_url))
    catalog_tags = {m["name"] for m in models}
    for m in upstream_models:
        name = m.get("name") or m.get("model") or ""
        # SUB-06: dedupe by the full tag, so qwen2.5-coder:7b stays visible next to the
        # catalog's qwen2.5-coder; only an identical tag (e.g. "<id>:latest") is shadowed.
        if name and name not in seen_ids and name not in catalog_tags:
            seen_ids.add(name)
            models.append(_upstream_model_entry(m, name))
    return models


def _ollama_tag_entry(m: Mapping[str, Any], now_iso: str) -> dict[str, Any]:
    """One /api/tags entry: real Ollama metadata for local tags, no invented size for routed models (SUB-06)."""
    if m.get("source") == "ollama-upstream":
        details = {"parent_model": "", "format": "gguf", "family": m["family"], "families": m["families"],
                   "parameter_size": m["parameter_size"], "quantization_level": "unknown",
                   **dict(m.get("details") or {})}
        return {"name": m["name"], "model": m["model"], "modified_at": m.get("modified_at") or now_iso,
                "size": m.get("size") or 0, "digest": m.get("digest") or "", "details": details}
    return {
        "name": m["name"], "model": m["model"], "modified_at": now_iso, "size": 0,
        "digest": f"sha256:subllm_{m['id'].replace('/', '_')}",
        "details": {"parent_model": "", "format": "remote", "family": m["family"], "families": m["families"],
                    "parameter_size": m["parameter_size"], "quantization_level": "remote"},
    }


def _extract_ticket(
    model_str: str,
    headers: Mapping[str, str],
    payload: Mapping[str, Any] | None = None,
) -> tuple[str, str | None]:
    """Extract ticket ID from model (@ticket-NNN), HTTP headers, or payload."""
    ticket: str | None = None
    clean_model = model_str

    if "@" in model_str:
        clean_model, suffix = model_str.split("@", 1)
        ticket_match = _TICKET_PATTERN.match(suffix)
        if ticket_match:
            ticket = ticket_match.group(1)

    if ticket is None:
        header_ticket = headers.get("X-Subactor-Ticket") or headers.get("X-Ticket")
        if header_ticket:
            ticket = header_ticket.strip()

    if ticket is None and payload:
        user = str(payload.get("user") or "")
        if user.startswith("ticket-"):
            ticket = user.strip()
        metadata = payload.get("metadata")
        if isinstance(metadata, dict) and "ticket" in metadata:
            ticket = str(metadata["ticket"]).strip()

    return clean_model, ticket


def _enabled_provider_policy(runtime_policy: Any, provider_id: str) -> Any | None:
    policy = runtime_policy.providers.get(provider_id) or runtime_policy.custom_providers.get(provider_id)
    return policy if policy is not None and policy.enabled else None


def _route_api_key(provider_id: str, provider_spec: Any, environment: Mapping[str, str]) -> str | None:
    """Credential for one provider route; None when the route is unusable (no CLI, invalid key)."""
    api_key = environment.get(provider_spec.api_key_env, "")
    if provider_id == "ollama" and not api_key:
        api_key = "ollama"
    if provider_spec.transport in CLI_EXECUTABLES:
        if shutil.which(CLI_EXECUTABLES[provider_spec.transport], path=environment.get("PATH")) is None:
            return None
        return ""
    if provider_spec.api_key_env and not credential_is_valid(provider_id, api_key):
        return None
    return api_key


def _build_model_resolved_routes(
    model_id: str,
    application: str = "subactor-proxy",
    function: str = "chat",
    environ: Mapping[str, str] | None = None,
) -> tuple[ResolvedRoute, ...]:
    """Build candidate ResolvedRoute objects for a specific model ID across valid providers."""
    environment = merged_environment(environ=environ)
    runtime_policy = load_policy_config(environ=environ)
    model_spec = MODELS.get(model_id)
    if model_spec is None or model_spec.forbidden:
        return ()

    app_spec = runtime_policy.applications.get(application) or runtime_policy.applications.get("subactor-proxy")
    app_name = app_spec.name if app_spec else application
    app_url = app_spec.url if app_spec else "https://github.com/subactor/subllm"

    order = routing_provider_order(environ=environment)
    candidates: list[ResolvedRoute] = []
    for provider_id, provider_model in model_spec.providers.items():
        provider_spec = PROVIDERS.get(provider_id)
        if not provider_spec or (order is not None and provider_id not in order):
            continue
        provider_policy = _enabled_provider_policy(runtime_policy, provider_id)
        if provider_policy is None:
            continue
        api_key = _route_api_key(provider_id, provider_spec, environment)
        if api_key is None:
            continue
        headers = ({"HTTP-Referer": app_url, "X-OpenRouter-Title": app_name}
                   if provider_spec.attribution_headers else {})
        priority = order.index(provider_id) * 10 if order is not None else provider_policy.priority
        candidates.append(
            ResolvedRoute(
                application=application,
                application_name=app_name,
                application_url=app_url,
                function=function,
                provider=provider_id,
                model=model_id,
                priority=priority,
                api_base=provider_spec.api_base,
                api_key_env=provider_spec.api_key_env,
                litellm_model=provider_model.litellm_model,
                wire_model=provider_model.wire_model,
                extra_headers=headers,
                transport=provider_spec.transport,
                modality="text",
                model_parameters=apply_parameters(provider_id, provider_model.wire_model, {}, environ=environment),
                api_key=api_key,
            )
        )

    return tuple(sorted(candidates, key=lambda c: c.priority))


def _safe_cwd() -> Path:
    """The current directory when it still exists, else HOME (CLI transports need a real cwd)."""
    try:
        cur = Path.cwd()
        if cur.exists():
            return cur
    except Exception:
        pass
    return Path.home()


def _route_attempt_budget(route: ResolvedRoute, messages: Sequence[Mapping[str, Any]], execution: Any,
                          environ: Mapping[str, str] | None) -> float:
    input_chars = sum(len(str(m.get("content", ""))) for m in messages if isinstance(m, Mapping))
    return resolve_attempt_timeout(route.provider, route.wire_model, environ=environ,
                                   default=execution.attempt_timeout_seconds, input_chars=input_chars)


def _complete_adaptive(adaptive_policy: Any, model_id: str, messages: Sequence[Mapping[str, Any]],
                       application: str, function: str, timeout_seconds: float, request_id: str,
                       response_format: Mapping[str, Any] | None,
                       environ: Mapping[str, str] | None) -> CompletionResponse:
    if ACTIVE_STREAM.get() is not None:
        raise stream_error("UNSUPPORTED-ADAPTIVE")
    return adaptive.execute(adaptive_policy, model_id, messages,
        build_routes=lambda model: _build_model_resolved_routes(model, application, function, environ=environ),
        invoke=_complete_route, timeout_seconds=timeout_seconds,
        response_format=response_format, request_id=request_id, environ=environ,
        minimum_class=adaptive_policy.get("routes", {}).get(f"{application}/{function}"))


def _complete_model_direct(
    model_id: str,
    messages: Sequence[Mapping[str, Any]],
    *,
    application: str = "subactor-proxy",
    function: str = "chat",
    timeout_seconds: float = 60.0,
    request_id: str | None = None,
    response_format: Mapping[str, Any] | None = None,
    environ: Mapping[str, str] | None = None,
) -> CompletionResponse:
    """Execute completion directly for a declared model with sequential failover across providers."""
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise CompletionError('timeout_seconds must be finite and greater than zero')
    request_id = request_id or uuid.uuid4().hex
    adaptive_policy = adaptive.policy(environ)
    if adaptive_policy and adaptive.requested_class(adaptive_policy, model_id) is not None:
        return _complete_adaptive(adaptive_policy, model_id, messages, application, function, timeout_seconds,
                                  request_id, response_format, environ)
    routes = _build_model_resolved_routes(model_id, application, function, environ=environ)
    if not routes:
        raise CompletionError(f"no available provider with valid credentials for model '{model_id}'")
    routes = supported_routes(routes)
    execution = load_policy_config(environ=environ).execution
    routes = order_with_last_resort(routes) if execution.failover_enabled else routes[:1]
    if not routes:
        raise CompletionError(f"all providers cooling down for model '{model_id}'")

    started_at = time.monotonic()
    failed_providers: set[str] = set()
    last_error: Exception | None = None
    for route in routes:
        if route.provider in failed_providers:
            continue
        elapsed = time.monotonic() - started_at
        attempt_budget = _route_attempt_budget(route, messages, execution, environ)
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            break
        attempt_timeout = min(remaining, attempt_budget)
        attempt_started = time.monotonic()
        try:
            response = _complete_route(route, messages, timeout_seconds=attempt_timeout, request_id=request_id,
                                       response_format=response_format, cwd=_safe_cwd())
        except _RetryableAttemptError as exc:
            if exc.provider_level:
                record_failure(route.provider, reason=exc.outcome,
                               latency_seconds=time.monotonic() - attempt_started, policy=execution)
                failed_providers.add(route.provider)
            last_error = exc
            if not execution.failover_enabled:
                raise CompletionError(str(exc)) from exc
            continue
        record_success(route.provider, latency_seconds=time.monotonic() - attempt_started, policy=execution)
        return response

    raise CompletionError(f"all candidates failed for model '{model_id}'") from last_error


def _write_proxy_receipt(
    ticket: str | None,
    application: str,
    function: str,
    model: str,
    response: CompletionResponse,
    duration_ms: int,
) -> None:
    """Persist an execution receipt when a ticket is indicated."""
    if not ticket:
        return
    try:
        receipts_dir = Path.home() / ".subactor" / "receipts"
        receipts_dir.mkdir(parents=True, exist_ok=True)
        ts_slug = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%SZ")
        filename = f"{ticket}--{ts_slug}--{response.provider}.json"
        receipt = {
            "schema": "subllm.proxy-receipt/v1",
            "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
            "ticket": ticket,
            "application": application,
            "function": function,
            "requested_model": model,
            "provider": response.provider,
            "wire_model": response.model,
            "usage": dict(response.usage),
            "duration_ms": duration_ms,
            "finish_reason": response.finish_reason,
            "status": "SUCCESS",
        }
        (receipts_dir / filename).write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    except Exception:
        pass


def _openai_usage(usage: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve an explicitly reported cache subset; do not add it to totals."""
    prompt = usage.get("input_tokens", usage.get("prompt_tokens", 0))
    completion = usage.get("output_tokens", usage.get("completion_tokens", 0))
    result = {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}
    details = usage.get("prompt_tokens_details")
    cached = usage.get("cached_input_tokens", details.get("cached_tokens") if isinstance(details, Mapping) else None)
    reported_prompt = usage.get("input_tokens", usage.get("prompt_tokens"))
    if type(cached) is int and type(reported_prompt) is int and 0 <= cached <= min(prompt, 10**12):
        result["prompt_tokens_details"] = {"cached_tokens": cached}
    return result


@dataclass(frozen=True)
class _DecideRequest:
    """Validated System One request options (SUB-08: parsed once, outside the handler)."""

    questions: list[Mapping[str, Any]]
    offline: bool
    allow_remote_fallback: bool
    requested_timeout: Any
    timeout: float
    temperature: float


def _bool_option(payload: Mapping[str, Any], key: str) -> bool:
    if key in payload and type(payload[key]) is not bool:
        raise ValueError(f"{key} must be a boolean")
    return bool(payload.get(key, False))


def _decide_timeout(requested_timeout: Any, offline: bool) -> float:
    try:
        timeout = (120.0 if offline else 8.0) if requested_timeout is None else float(requested_timeout)
    except (TypeError, ValueError):
        timeout = math.nan
    if isinstance(requested_timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and greater than zero")
    return timeout


def _decide_temperature(value: Any) -> float:
    try:
        temperature = float(value)
    except (TypeError, ValueError):
        return 0.2
    return temperature if math.isfinite(temperature) else 0.2


def _parse_decide_request(payload: Any) -> _DecideRequest:
    """Validate a System One request; ValueError messages are the 400 INVALID_REQUEST texts."""
    if not isinstance(payload, Mapping):
        raise ValueError("JSON object payload is required")
    questions = payload.get("questions")
    if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes)) or not questions:
        raise ValueError("questions array is required")
    valid_questions = [q for q in questions if isinstance(q, Mapping) and str(q.get("id") or "").strip()]
    if not valid_questions:
        raise ValueError("at least one valid question with id is required")
    offline = _bool_option(payload, "offline")
    allow_remote_fallback = _bool_option(payload, "allow_remote_fallback")
    from .decisions import parse_keep_alive

    parse_keep_alive(payload.get("keep_alive"))
    requested_timeout = payload.get("timeout")
    return _DecideRequest(
        questions=valid_questions,
        offline=offline,
        allow_remote_fallback=allow_remote_fallback,
        requested_timeout=requested_timeout,
        timeout=_decide_timeout(requested_timeout, offline),
        temperature=_decide_temperature(payload.get("temperature", 0.2)),
    )


def _keep_alive_kwargs(payload: Mapping[str, Any]) -> dict[str, Any]:
    from .decisions import parse_keep_alive

    return {"keep_alive": parse_keep_alive(payload["keep_alive"])} if payload.get("keep_alive") is not None else {}


def _is_explicit_route(model: str) -> bool:
    return "/" in model and tuple(model.split("/", 1)) in ROUTES


def _decide_route_flags(clean_model: str) -> tuple[bool, bool]:
    """``(is_known_target, prefers_explicit_route)`` for a requested System One model."""
    explicit = _is_explicit_route(clean_model)
    return clean_model in MODELS or explicit, (clean_model in MODELS and not clean_model.startswith("qwen")) or explicit


def _requested_timeout(payload: Mapping[str, Any], default: float) -> float:
    """Request ``timeout`` (or ``default``); ValueError when it is not finite and positive."""
    requested = payload.get("timeout")
    try:
        timeout = default if requested is None else float(requested)
    except (TypeError, ValueError):
        timeout = math.nan
    if isinstance(requested, bool) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be finite and greater than zero")
    return timeout


def _ollama_usage_counts(response: CompletionResponse) -> tuple[Any, Any]:
    usage = response.usage
    return (usage.get("input_tokens", usage.get("prompt_tokens", 0)),
            usage.get("output_tokens", usage.get("completion_tokens", 0)))


def _ollama_done_fields(response: CompletionResponse, duration_ms: int) -> dict[str, Any]:
    prompt_tokens, eval_tokens = _ollama_usage_counts(response)
    return {"done": True, "total_duration": duration_ms * 1_000_000, "load_duration": 1_000_000,
            "prompt_eval_count": prompt_tokens, "eval_count": eval_tokens}


class SubLLMProxyHandler(BaseHTTPRequestHandler):
    ollama_upstream: str = DEFAULT_OLLAMA_UPSTREAM
    server_version = "subllm-proxy/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _request_origin(self) -> str | None:
        origin = self.headers.get("Origin") if self.headers is not None else None
        return origin if origin is not None and origin.strip() else None

    def _reject_foreign_origin(self) -> bool:
        """403 PROXY-ORIGIN for a browser request from an origin that is not allowed."""
        origin = self._request_origin()
        if origin is None or proxy_origin_allowed(origin):
            return False
        self._error(403, "PROXY-ORIGIN", "request origin is not allowed")
        return True

    def _send_cors_headers(self) -> None:
        self.send_header("Vary", "Origin")
        origin = self._request_origin()
        if origin is None or not proxy_origin_allowed(origin):
            return
        self.send_header("Access-Control-Allow-Origin", origin.strip())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, Cache-Control, Pragma, X-Ticket, X-Subactor-Ticket, "
            "X-Application, X-Subactor-Application, X-Function, X-Subactor-Function, X-Request-ID",
        )
        self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self) -> None:
        if self._reject_foreign_origin():
            return
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def _catalog_models(self) -> list[dict[str, Any]]:
        policy = self.headers.get("Cache-Control", "").lower()
        directives = {part.split("=", 1)[0].strip() for part in policy.split(",")}
        fresh = bool(directives & {"no-store", "no-cache"}) or bool(
            re.search(r'(?:^|,)\s*max-age\s*=\s*"?0+"?\s*(?:,|$)', policy)
        ) or "no-cache" in {part.strip().lower() for part in self.headers.get("Pragma", "").split(",")}
        return list_proxy_models(self.ollama_upstream, fresh=fresh)

    def do_GET(self) -> None:
        if not self._local_host():
            self._error(421, "PROXY-001", "host is not a local bind")
            return
        if self._reject_foreign_origin():
            return

        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/v1/ai/capabilities":
            from .audio import speech_capabilities
            self._json(200, speech_capabilities())
            return

        if path in {"", "/", "/health"}:
            self._json(200, {
                "status": "ok",
                "service": "subllm-proxy",
                "version": _package_version(),
                "upstream_ollama": is_upstream_ollama_alive(self.ollama_upstream, fresh=True),
            })
            return

        if path == "/v1/models":
            models = self._catalog_models()
            data = [
                {
                    "id": m["id"],
                    "object": "model",
                    "created": 1789747200,
                    "owned_by": m["source"],
                    "permission": [],
                }
                for m in models
            ]
            self._json(200, {"object": "list", "data": data})
            return

        if path == "/api/tags":
            models = self._catalog_models()
            now_iso = datetime.datetime.now(datetime.UTC).isoformat()
            ollama_models = [_ollama_tag_entry(m, now_iso) for m in models]
            self._json(200, {"models": ollama_models})
            return

        if path == "/api/version":
            self._json(200, {"version": "0.5.2-subllm"})
            return

        # Upstream proxy fallback
        if is_upstream_ollama_alive(self.ollama_upstream):
            self._forward_upstream("GET", path, None)
            return

        self._error(404, "PROXY-404", f"path '{path}' is not registered")

    # Ordered POST routes: (path set, handler method, response_format schema gate).
    _POST_ROUTES: tuple[tuple[frozenset[str], str, bool], ...] = (
        (frozenset({"/v1/decide/warmup"}), "_handle_decide_warmup", False),
        (frozenset({"/v1/decide", "/v1/system-one/decide"}), "_handle_system_one_decide", True),
        (frozenset({"/v1/chat/completions"}), "_handle_openai_chat_completions", True),
        (frozenset({"/api/chat"}), "_handle_ollama_chat", True),
        (frozenset({"/api/generate"}), "_handle_ollama_generate", True),
        (frozenset({"/api/show"}), "_handle_ollama_show", False),
    )

    def _handle_speech(self, path: str, payload: Any) -> None:
        from .audio import SpeechError, synthesize, transcribe
        try:
            result = (transcribe if path.endswith("transcribe") else synthesize)(payload)
        except SpeechError as error:
            self._error(error.status, error.code, str(error))
        except Exception:
            self._error(503, "SPEECH_BACKEND_UNAVAILABLE", "Speech inference could not be completed")
        else:
            self._json(200, result)

    def _schema_gate_rejects(self, payload: Any) -> bool:
        try:
            declared_schema_gate(payload.get("response_format"), None)
        except CompletionError as exc:
            if not self._handle_contract_error(exc):
                self._error(500, "COMPLETION_FAILED", str(exc))
            return True
        return False

    def do_POST(self) -> None:
        if not self._local_host():
            self._error(421, "PROXY-001", "host is not a local bind")
            return
        if self._reject_foreign_origin():
            return
        path = urlparse(self.path).path
        payload = self._read_json()
        if payload is None:
            return
        if path in {"/v1/speech/transcribe", "/v1/speech/synthesize"}:
            self._handle_speech(path, payload)
            return
        for paths, handler, gated in self._POST_ROUTES:
            if path in paths:
                if gated and self._schema_gate_rejects(payload):
                    return
                getattr(self, handler)(payload)
                return
        # Upstream Ollama forward fallback
        if is_upstream_ollama_alive(self.ollama_upstream):
            self._forward_upstream("POST", path, payload)
            return
        self._error(404, "PROXY-404", f"path '{path}' is not registered")

    def _handle_decide_warmup(self, payload: Any) -> None:
        """SUB-03: load the local decision model before the first decision after idle."""
        from .decisions import DecisionError, warmup

        if not isinstance(payload, Mapping):
            self._error(400, "INVALID_REQUEST", "JSON object payload is required")
            return
        timeout = payload.get("timeout", 120.0)
        try:
            result = warmup(payload.get("model") or None, base_url=self.ollama_upstream,
                            keep_alive=payload.get("keep_alive", 300),
                            timeout_seconds=float(timeout) if type(timeout) in (int, float) else timeout)
        except ValueError as exc:
            self._error(400, "INVALID_REQUEST", str(exc))
            return
        except DecisionError:
            self._error(503, "LOCAL_DECISION_UNAVAILABLE", "local decision model could not be loaded")
            return
        self._json(200, result, extra_headers={"X-Subactor-Provider": "ollama"})

    def _decide_attribution(self) -> tuple[str | None, str | None]:
        # SUB-02: a request without application headers is not attributed to heyasa/command.
        declared_app = self.headers.get("X-Subactor-Application") or self.headers.get("X-Application")
        declared_func = self.headers.get("X-Subactor-Function") or self.headers.get("X-Function")
        return declared_app, declared_func

    def _decide_offline(self, payload: Mapping[str, Any], clean_model: str, timeout: float,
                        app: str, func: str, req_id: str) -> None:
        from .decisions import DecisionError, decide_legacy

        started = time.monotonic()
        try:
            result = decide_legacy(dict(payload, model=clean_model), base_url=self.ollama_upstream,
                                   timeout_seconds=timeout, application=app, function=func, request_id=req_id,
                                   **_keep_alive_kwargs(payload))
        except ValueError:
            self._error(400, "INVALID_REQUEST", "Invalid offline decision request")
            return
        except DecisionError:
            self._error(503, "OFFLINE_DECISION_UNAVAILABLE", "Local decision inference unavailable")
            return
        duration_ms = round((time.monotonic() - started) * 1000)
        self._json(200, {**result, "schema": SYSTEM_ONE_RESPONSE_SCHEMA, "id": req_id,
                         "requested_model": clean_model, "duration_ms": duration_ms}, extra_headers={
                             "X-Subactor-Provider": "ollama", "X-Subactor-Model": result["model"],
                             "X-Subactor-Duration-Ms": str(duration_ms),
                         })

    def _decide_locally(self, upstream: str, clean_model: str, messages: list[dict[str, str]],
                        payload: Mapping[str, Any], request: _DecideRequest, app: str, func: str,
                        req_id: str) -> tuple[CompletionResponse | None, Exception | None]:
        """Local Ollama attempt, then the small-Qwen fallback when a d1 model failed."""
        # SUB-03: a cold local model gets the caller's budget (up to 120 s), not a fixed 6 s.
        local_timeout = 6.0 if request.requested_timeout is None else min(request.timeout, 120.0)
        last_error: Exception | None = None
        local_model = _select_local_system_one_ollama_model(clean_model, upstream)
        if local_model is not None:
            try:
                return _complete_ollama_system_one(
                    upstream, local_model, messages, temperature=request.temperature,
                    timeout_seconds=local_timeout, request_payload=payload,
                    application=app, function=func, request_id=req_id,
                ), None
            except Exception as exc:
                last_error = exc
        if not (local_model and _is_d1(local_model)):
            return None, last_error
        qwen_fallback = _select_local_system_one_ollama_model("qwen3.5:0.8b", upstream, exclude_d1=True)
        if not qwen_fallback:
            return None, last_error
        try:
            return _complete_ollama_system_one(
                upstream, qwen_fallback, messages, temperature=request.temperature, timeout_seconds=local_timeout,
            ), None
        except Exception as exc:
            return None, exc

    def _refuse_remote_decide(self, request: _DecideRequest, is_known_target: bool,
                              declared: tuple[str | None, str | None], last_error: Exception | None,
                              upstream: str, clean_model: str, req_id: str) -> bool:
        """SUB-02: decision state leaves the host only for an explicitly requested route
        or with allow_remote_fallback: true and a declared application route."""
        if not request.allow_remote_fallback:
            refusal = "remote_fallback_not_allowed"
        elif not is_known_target and not all(declared):
            refusal = "remote_fallback_route_unspecified"
        else:
            return False
        reason = type(last_error).__name__ if last_error is not None else (
            "local_model_unavailable" if is_upstream_ollama_alive(upstream) else "ollama_unavailable")
        self._json(503, {"error": {
            "code": "LOCAL_DECISION_UNAVAILABLE",
            "message": "local decision inference failed and remote fallback was not used",
            "reason": reason, "remote_fallback": refusal, "provider": None,
            "requested_model": clean_model, "id": req_id,
        }}, extra_headers={"X-Subactor-Remote-Fallback": "refused"})
        return True

    def _decide_remotely(self, payload: Mapping[str, Any], messages: list[dict[str, str]], fallback_model: str,
                         app: str, func: str, timeout: float, req_id: str) -> CompletionResponse | None:
        """Routed fallback; None means an error response was already sent."""
        fallback_payload = dict(payload)
        fallback_payload.setdefault("response_format", {"type": "json_object"})
        try:
            return self._execute_model_or_route(fallback_model, messages, app, func, timeout, req_id,
                                                fallback_payload)
        except Exception as exc:
            if not self._handle_contract_error(exc):
                self._error(500, "COMPLETION_FAILED", str(exc))
            return None

    def _send_decide_result(self, payload: Mapping[str, Any], request: _DecideRequest, response: CompletionResponse,
                            clean_model: str, ticket: str | None, req_id: str, duration_ms: int) -> None:
        parsed = _extract_json_object(response.content)
        probabilities, answers = _normalize_system_one_probabilities(request.questions, parsed)
        extra_headers = {
            "X-Subactor-Provider": response.provider,
            "X-Subactor-Model": response.model,
            "X-Subactor-Duration-Ms": str(duration_ms),
        }
        if ticket:
            extra_headers["X-Subactor-Ticket"] = ticket
        self._json(
            200,
            {
                "schema": SYSTEM_ONE_RESPONSE_SCHEMA,
                "id": req_id,
                "provider": response.provider,
                "model": response.model,
                "requested_model": clean_model,
                "wire_format": str(payload.get("wire_format") or "jev-system-one"),
                "probabilities": probabilities,
                "answers": answers,
                "usage": dict(response.usage),
                "duration_ms": duration_ms,
            },
            extra_headers=extra_headers,
        )

    def _handle_system_one_decide(self, payload: Mapping[str, Any]) -> None:
        try:
            request = _parse_decide_request(payload)
        except ValueError as exc:
            self._error(400, "INVALID_REQUEST", str(exc))
            return
        clean_model, ticket = _extract_ticket(str(payload.get("model") or "d1:3b"), self.headers, payload)
        declared = self._decide_attribution()
        app, func = declared[0] or "subactor-proxy", declared[1] or "decide"
        req_id = f"sysone-{uuid.uuid4().hex[:12]}"
        if request.offline:
            self._decide_offline(payload, clean_model, request.timeout, app, func, req_id)
            return
        messages = _build_system_one_messages(payload)
        t0 = time.monotonic()
        response: CompletionResponse | None = None
        last_error: Exception | None = None
        upstream = _resolve_system_one_ollama_upstream(self.ollama_upstream)
        is_known_target, prefers_explicit_route = _decide_route_flags(clean_model)
        if not prefers_explicit_route and is_upstream_ollama_alive(upstream):
            response, last_error = self._decide_locally(upstream, clean_model, messages, payload, request,
                                                        app, func, req_id)
        if response is None:
            if not prefers_explicit_route and self._refuse_remote_decide(
                    request, is_known_target, declared, last_error, upstream, clean_model, req_id):
                return
            response = self._decide_remotely(payload, messages, clean_model if is_known_target else f"{app}/{func}",
                                             app, func, request.timeout, req_id)
            if response is None:
                return
        duration_ms = round((time.monotonic() - t0) * 1000)
        _write_proxy_receipt(ticket, app, func, clean_model, response, duration_ms)
        self._send_decide_result(payload, request, response, clean_model, ticket, req_id, duration_ms)

    def _handle_openai_chat_completions(self, payload: Mapping[str, Any]) -> None:
        from .runtime_profile import ProfileError, request_parameter_scope
        try:
            with request_parameter_scope(payload):
                self._handle_openai_chat_completions_with_parameters(payload)
        except ProfileError as error:
            self._error(400, "INVALID_REQUEST", str(error))

    def _fast_forward_to_ollama(self, clean_model: str, path: str, payload: Mapping[str, Any]) -> bool:
        """Models unknown to SubLLM policy go straight to the local Ollama when it is up."""
        if (not adaptive.policy() and clean_model not in MODELS and "/" not in clean_model
                and is_upstream_ollama_alive(self.ollama_upstream)):
            self._forward_upstream("POST", path, payload)
            return True
        return False

    def _complete_or_forward(self, clean_model: str, messages: Any, app: str | None, func: str | None,
                             timeout: float, req_id: str | None, payload: Mapping[str, Any],
                             forward_path: str) -> CompletionResponse | None:
        """Routed completion; on failure the local Ollama forward or an error. None: a response was sent."""
        try:
            return self._execute_model_or_route(clean_model, messages, app, func, timeout, req_id, payload)
        except Exception as exc:
            if self._handle_contract_error(exc):
                return None
            if not adaptive.policy() and is_upstream_ollama_alive(self.ollama_upstream):
                self._forward_upstream("POST", forward_path, payload)
                return None
            self._error(500, "COMPLETION_FAILED", str(exc))
            return None

    @staticmethod
    def _completion_headers(response: CompletionResponse, duration_ms: int, ticket: str | None) -> dict[str, str]:
        headers = {
            "X-Subactor-Provider": response.provider,
            "X-Subactor-Model": response.model,
            "X-Subactor-Duration-Ms": str(duration_ms),
        }
        if ticket:
            headers["X-Subactor-Ticket"] = ticket
        return headers

    def _handle_openai_chat_completions_with_parameters(self, payload: Mapping[str, Any]) -> None:
        clean_model, ticket = _extract_ticket(str(payload.get("model") or "glm-5.3"), self.headers, payload)
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            self._error(400, "INVALID_REQUEST", "messages array is required")
            return
        try:
            timeout = _requested_timeout(payload, load_policy_config().execution.attempt_timeout_seconds)
        except ValueError as exc:
            self._error(400, "INVALID_REQUEST", str(exc))
            return
        req_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created_ts = int(time.time())
        app, func = self._decide_attribution()
        if self._fast_forward_to_ollama(clean_model, "/v1/chat/completions", payload):
            return
        if bool(payload.get("stream", False)):
            from .proxy_stream import serve_stream
            serve_stream(self, payload, clean_model, app, func, timeout, req_id, ticket,
                         protocol="openai", created=created_ts)
            return
        t0 = time.monotonic()
        response = self._complete_or_forward(clean_model, messages, app, func, timeout, req_id, payload,
                                             "/v1/chat/completions")
        if response is None:
            return
        duration_ms = round((time.monotonic() - t0) * 1000)
        _write_proxy_receipt(ticket, app or "subactor-proxy", func or "chat", clean_model, response, duration_ms)
        self._json(200, {
            "id": req_id,
            "object": "chat.completion",
            "created": created_ts,
            "model": response.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": response.content},
                "finish_reason": response.finish_reason or "stop",
            }],
            "usage": _openai_usage(response.usage),
        }, extra_headers=self._completion_headers(response, duration_ms, ticket))


    def _handle_ollama_chat(self, payload: Mapping[str, Any]) -> None:
        from .runtime_profile import ProfileError, ollama_parameter_scope
        options = payload.get("options", {})
        clean_model, _ticket = _extract_ticket(str(payload.get("model") or "glm-5.3"), self.headers, payload)
        if not options:
            return self._handle_ollama_chat_with_parameters(payload)
        if (not adaptive.policy() and clean_model not in MODELS and "/" not in clean_model
                and is_upstream_ollama_alive(self.ollama_upstream)):
            self._forward_upstream("POST", "/api/chat", payload)
            return
        try:
            with ollama_parameter_scope(options):
                self._handle_ollama_chat_with_parameters(payload)
        except ProfileError as error:
            self._error(400, "INVALID_REQUEST", str(error))

    def _handle_ollama_chat_with_parameters(self, payload: Mapping[str, Any]) -> None:
        clean_model, ticket = _extract_ticket(str(payload.get("model") or "glm-5.3"), self.headers, payload)
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            self._error(400, "INVALID_REQUEST", "messages array is required")
            return
        # Ollama defaults to stream: true unless stream: false is explicitly sent
        stream = payload.get("stream", True)
        timeout = 60.0
        now_iso = datetime.datetime.now(datetime.UTC).isoformat()
        app, func = self._decide_attribution()
        if self._fast_forward_to_ollama(clean_model, "/api/chat", payload):
            return
        if stream:
            from .proxy_stream import serve_stream
            serve_stream(self, payload, clean_model, app, func, timeout, None, ticket,
                         protocol="ollama", created=now_iso)
            return
        t0 = time.monotonic()
        response = self._complete_or_forward(clean_model, messages, app, func, timeout, None, payload, "/api/chat")
        if response is None:
            return
        duration_ms = round((time.monotonic() - t0) * 1000)
        _write_proxy_receipt(ticket, app or "subactor-proxy", func or "chat", clean_model, response, duration_ms)
        self._json(200, {
            "model": response.model,
            "created_at": now_iso,
            "message": {"role": "assistant", "content": response.content},
            **_ollama_done_fields(response, duration_ms),
        }, extra_headers=self._completion_headers(response, duration_ms, ticket))

    def _stream_ollama_generate(self, response: CompletionResponse, now_iso: str, duration_ms: int,
                                extra_headers: Mapping[str, str]) -> None:
        self.close_connection = True
        self.send_response(200)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        for k, v in extra_headers.items():
            self.send_header(k, v)
        self.end_headers()
        content = response.content
        chunk_size = 32
        for i in range(0, len(content), chunk_size):
            chunk_line = {"model": response.model, "created_at": now_iso,
                          "response": content[i : i + chunk_size], "done": False}
            self.wfile.write((json.dumps(chunk_line) + "\n").encode("utf-8"))
            self.wfile.flush()
        done_line = {"model": response.model, "created_at": now_iso, "response": "",
                     **_ollama_done_fields(response, duration_ms)}
        self.wfile.write((json.dumps(done_line) + "\n").encode("utf-8"))
        self.wfile.flush()

    def _handle_ollama_generate(self, payload: Mapping[str, Any]) -> None:
        clean_model, ticket = _extract_ticket(str(payload.get("model") or "glm-5.3"), self.headers, payload)
        prompt = str(payload.get("prompt") or "")
        system = str(payload.get("system") or "")
        messages: list[dict[str, str]] = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": prompt or " "})
        stream = payload.get("stream", True)
        timeout = 60.0
        now_iso = datetime.datetime.now(datetime.UTC).isoformat()
        app, func = self._decide_attribution()
        if self._fast_forward_to_ollama(clean_model, "/api/generate", payload):
            return
        t0 = time.monotonic()
        response = self._complete_or_forward(clean_model, messages, app, func, timeout, None, payload,
                                             "/api/generate")
        if response is None:
            return
        duration_ms = round((time.monotonic() - t0) * 1000)
        _write_proxy_receipt(ticket, app or "subactor-proxy", func or "chat", clean_model, response, duration_ms)
        extra_headers = self._completion_headers(response, duration_ms, ticket)
        if stream:
            self._stream_ollama_generate(response, now_iso, duration_ms, extra_headers)
            return
        self._json(200, {
            "model": response.model,
            "created_at": now_iso,
            "response": response.content,
            **_ollama_done_fields(response, duration_ms),
        }, extra_headers=extra_headers)


    def _handle_ollama_show(self, payload: Mapping[str, Any]) -> None:
        name = str(payload.get("name") or payload.get("model") or "glm-5.3")
        base = name.split(":")[0]
        # Only the catalog's own names are routed (``id`` or ``id:latest``); any other tag, e.g.
        # qwen2.5-coder:7b, is local and described by Ollama even when /api/tags is slow.
        routed = (name == base or name == f"{base}:latest") and (
            base in MODELS or any(f"{app}/{func}" == base for app, func in ROUTES))
        local = routed and name in {m.get("name") for m in get_upstream_ollama_models(self.ollama_upstream)}
        if (local or not routed) and is_upstream_ollama_alive(self.ollama_upstream):
            # SUB-06: a local tag is described by Ollama itself, not by a synthetic subllm modelfile.
            self._forward_upstream("POST", "/api/show", payload)
            return
        family = _model_family(base)
        self._json(200, {
            "license": "Governed by Subactor policy",
            "modelfile": f"FROM subllm:{base}\nPARAMETER temperature 0.7\n",
            "parameters": "temperature 0.7",
            "template": "{{ .Prompt }}",
            "details": {
                "parent_model": "",
                "format": "gguf",
                "family": family,
                "families": [family],
                "parameter_size": "unknown",
                "quantization_level": "remote",
            },
        })

    def _execute_model_or_route(
        self,
        clean_model: str,
        messages: Sequence[Mapping[str, Any]],
        app: str | None,
        func: str | None,
        timeout: float,
        req_id: str | None,
        payload: Mapping[str, Any],
    ) -> CompletionResponse:
        require_route_bearer(getattr(self, "headers", None))
        effective_timeout = timeout
        response_format = payload.get("response_format")

        adaptive_policy = adaptive.policy()
        if adaptive_policy and adaptive.requested_class(adaptive_policy, clean_model) is not None:
            return _complete_model_direct(clean_model, messages, application=app or "subactor-proxy",
                function=func or "chat", timeout_seconds=effective_timeout,
                request_id=req_id, response_format=response_format)

        # 1. Direct application/function notation e.g. "koru-agent/queue-executor"
        if "/" in clean_model:
            target_app, target_func = clean_model.split("/", 1)
            return complete(target_app, target_func, messages, timeout_seconds=effective_timeout, request_id=req_id,
                            response_format=response_format)

        # 2. If app and func specified from headers and exists in ROUTES
        if app and func and (app, func) in ROUTES:
            return complete(app, func, messages, timeout_seconds=effective_timeout, request_id=req_id,
                            response_format=response_format)

        # 3. Model is a known catalog model in MODELS
        if clean_model in MODELS:
            return _complete_model_direct(
                clean_model,
                messages,
                application=app or "subactor-proxy",
                function=func or "chat",
                timeout_seconds=effective_timeout,
                request_id=req_id,
                response_format=response_format,
            )

        if adaptive_policy:
            raise CompletionError("unknown model: declare a replacement class or an explicit route")

        # 4. Fallback to default subactor-proxy/chat
        return complete("subactor-proxy", "chat", messages, timeout_seconds=effective_timeout, request_id=req_id,
                        response_format=response_format)

    def _forward_upstream(self, method: str, path: str, payload: Any | None) -> None:
        url = f"{self.ollama_upstream.rstrip('/')}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"}
        req = Request(url, data=data, headers=headers, method=method)
        timeout = upstream_forward_timeout(payload)
        started = time.monotonic()
        try:
            with urlopen(req, timeout=timeout) as resp:
                body = resp.read()
                self._record_forward(method, path, payload, started, resp.status, None, body)
                self.send_response(resp.status)
                self._send_cors_headers()
                for k, v in resp.headers.items():
                    if k.lower() not in {"transfer-encoding", "content-length", "access-control-allow-origin"}:
                        self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
        except HTTPError as exc:
            body = exc.read()
            self._record_forward(method, path, payload, started, exc.code, f"HTTP_{exc.code}", b"")
            self.send_response(exc.code)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (TimeoutError, URLError) as exc:
            if isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError):
                self._record_forward(method, path, payload, started, 504, "UPSTREAM_TIMEOUT", b"")
                self._error(504, "UPSTREAM_TIMEOUT", f"upstream Ollama did not answer within {timeout:g} s")
            else:
                self._record_forward(method, path, payload, started, 502, "UPSTREAM_UNAVAILABLE", b"")
                self._error(502, "UPSTREAM_UNAVAILABLE", f"failed to connect to upstream Ollama: {exc.reason}")

    def _record_forward(self, method: str, path: str, payload: Any, started: float, status: int,
                        diagnostic: str | None, body: bytes) -> None:
        """One usage attempt per raw Ollama forward, attributed from the request headers (SUB-04)."""
        if method != "POST" or path not in FORWARD_USAGE_PATHS:
            return
        headers = getattr(self, "headers", None) or {}
        model = payload.get("model") if isinstance(payload, dict) else None
        record_attempt(
            request_id=headers.get("X-Request-ID") or f"forward-{uuid.uuid4().hex[:12]}",
            application=headers.get("X-Subactor-Application") or headers.get("X-Application") or "subactor-proxy",
            function=headers.get("X-Subactor-Function") or headers.get("X-Function") or "forward",
            provider="ollama", model=model if isinstance(model, str) else "unknown",
            status="success" if 200 <= status < 300 else "error", diagnostic_code=diagnostic,
            duration_ms=int((time.monotonic() - started) * 1000),
            usage=forward_usage_counts(path, body) if 200 <= status < 300 else {},
        )

    def _local_host(self) -> bool:
        host = (self.headers.get("Host") or "").split(":", 1)[0].strip().lower()
        return host in ALLOWED_HOSTS

    def _read_json(self) -> Any | None:
        length = self.headers.get("Content-Length")
        if length is None:
            self._error(400, "PROXY-001", "content length is required")
            return None
        try:
            size = int(length)
        except ValueError:
            self._error(400, "PROXY-001", "content length is invalid")
            return None
        if size < 2 or size > 10_000_000:
            self._error(400, "PROXY-001", "request body size is outside bounds")
            return None
        try:
            return json.loads(self.rfile.read(size).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._error(400, "PROXY-001", "request body is not JSON")
            return None

    def _json(self, status: int, payload: Any, extra_headers: Mapping[str, str] | None = None) -> None:
        body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, code: str, message: str) -> None:
        self._json(status, {"error": {"code": code, "message": message}})

    def _handle_contract_error(self, error: Exception) -> bool:
        """Never send an invalid or unavailable acceptance gate to raw upstream."""
        if isinstance(error, ProxyUnauthorizedError):
            self._error(401, "PROXY-AUTH", str(error))
        elif isinstance(error, InvalidResponseContractError):
            self._error(400, "INVALID_REQUEST", str(error))
        elif getattr(error, "diagnostic_code", None) == QUALITY_VALIDATOR_ERROR_CODE:
            self._error(500, "COMPLETION_FAILED", str(error))
        elif getattr(error, "diagnostic_code", None) == "SUBLLM-PARAMETERS-UNSUPPORTED":
            self._error(400, "INVALID_REQUEST", str(error))
        else:
            return False
        return True


def make_proxy_server(
    host: str = "127.0.0.1",
    port: int = DEFAULT_PROXY_PORT,
    ollama_upstream: str = DEFAULT_OLLAMA_UPSTREAM,
) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SubLLMError("server bind is not local")
    handler = type("BoundSubLLMProxyHandler", (SubLLMProxyHandler,), {"ollama_upstream": ollama_upstream})
    return ThreadingHTTPServer((host, port), handler)


def serve_proxy(
    host: str = "127.0.0.1",
    port: int = DEFAULT_PROXY_PORT,
    ollama_upstream: str = DEFAULT_OLLAMA_UPSTREAM,
) -> None:
    server = make_proxy_server(host, port, ollama_upstream)
    try:
        server.serve_forever()
    finally:
        server.server_close()
