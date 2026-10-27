from __future__ import annotations

import datetime
import json
import math
import os
import re
import shutil
import sqlite3
import time
import uuid
from collections.abc import Mapping, Sequence
from functools import lru_cache
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from .errors import CompletionError, SubLLMError
from .health import order_by_health, record_failure, record_success
from .openrouter_routing import apply_parameters
from .policy import MODELS, PROVIDERS, ROUTES
from .policy_config import load_policy_config, resolve_attempt_timeout
from .provider_order import routing_provider_order
from .types import ResolvedRoute

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
DEFAULT_OLLAMA_UPSTREAM = "http://127.0.0.1:11434"
DEFAULT_PROXY_PORT = 11435
SYSTEM_ONE_REQUEST_SCHEMA = "wellmanifest.system-one-request/v1"
SYSTEM_ONE_RESPONSE_SCHEMA = "wellmanifest.system-one-response/v1"
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

_TICKET_PATTERN = re.compile(r"^(ticket-[A-Za-z0-9_.-]+)")


def _resolve_system_one_ollama_upstream(configured_upstream: str) -> str:
    """Resolve an active local Ollama upstream for System One, falling back to DEFAULT_OLLAMA_UPSTREAM."""
    if is_upstream_ollama_alive(configured_upstream):
        return configured_upstream
    if configured_upstream != DEFAULT_OLLAMA_UPSTREAM and is_upstream_ollama_alive(DEFAULT_OLLAMA_UPSTREAM):
        return DEFAULT_OLLAMA_UPSTREAM
    return configured_upstream


def _select_local_system_one_ollama_model(
    requested_model: str,
    upstream_url: str = DEFAULT_OLLAMA_UPSTREAM,
) -> str | None:
    """Select an installed local Ollama model matching the System One profile or Qwen3.5 backbone."""
    installed = get_upstream_ollama_models(upstream_url)
    if not installed:
        return None
    installed_names = [
        str(m.get("name") or m.get("model") or "").strip()
        for m in installed
        if str(m.get("name") or m.get("model") or "").strip()
    ]
    if not installed_names:
        return None
    installed_set = set(installed_names)
    req = requested_model.strip()
    req_low = req.lower()

    if req in installed_set:
        return req
    if f"{req}:latest" in installed_set:
        return f"{req}:latest"

    preferred_candidates: list[str] = []
    if any(k in req_low for k in ("0.8b", "0.6b", "0.5b", "322m", "340m", "270m", "laya", "nanojev", "jevlike")):
        preferred_candidates.extend(["qwen3.5:0.8b", "willman-eval:qwen3.5-0.8b", "qwen2.5:1.5b"])
    elif "2b" in req_low:
        preferred_candidates.extend(["qwen3.5:2b", "willman-eval:qwen3.5-2b", "qwen3.5:0.8b"])
    elif any(k in req_low for k in ("4b", "kev", "semif", "jevos")):
        preferred_candidates.extend(["qwen3.5:4b", "willman-eval:qwen3.5-4b", "qwen3.5:0.8b"])

    for candidate in [*preferred_candidates, *SYSTEM_ONE_LOCAL_OLLAMA_MODELS]:
        if candidate in installed_set:
            return candidate
    return installed_names[0]


def _normalize_question_options(raw_options: Any, q_type: str) -> tuple[list[str], dict[str, str]]:
    """Extract ordered option keys and optional human descriptions from a System One question."""
    if isinstance(raw_options, Mapping):
        keys = [str(k) for k in raw_options if str(k)]
        descriptions = {str(k): str(v) for k, v in raw_options.items() if str(k)}
        return keys, descriptions
    if isinstance(raw_options, Sequence) and not isinstance(raw_options, (str, bytes)):
        keys = [str(x) for x in raw_options if str(x)]
        return keys, {}
    if q_type == "noul":
        return ["true", "false"], {}
    if q_type == "score":
        return ["1", "2", "3"], {}
    return [], {}


def _extract_json_object(raw_text: str) -> dict[str, Any]:
    """Parse JSON object from model output, tolerating markdown fences."""
    cleaned = raw_text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(cleaned[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
    return {}


def _normalize_system_one_probabilities(
    questions: Sequence[Mapping[str, Any]],
    parsed_output: Mapping[str, Any],
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Normalize raw model probabilities or chosen answers into valid probability distributions."""
    raw_probs = parsed_output.get("probabilities")
    raw_probs_map = raw_probs if isinstance(raw_probs, Mapping) else {}
    raw_answers = parsed_output.get("answers")
    raw_answers_map = raw_answers if isinstance(raw_answers, Mapping) else {}

    probabilities: dict[str, dict[str, float]] = {}
    answers: dict[str, Any] = {}

    for q in questions:
        q_id = str(q.get("id") or "").strip()
        if not q_id:
            continue
        q_type = str(q.get("type") or "choice").strip().lower()
        option_keys, _ = _normalize_question_options(q.get("options"), q_type)
        if not option_keys:
            continue

        dist: dict[str, float] = {}
        q_prob_candidate = raw_probs_map.get(q_id)
        if not isinstance(q_prob_candidate, Mapping) and isinstance(parsed_output.get(q_id), Mapping):
            q_prob_candidate = parsed_output.get(q_id)

        if isinstance(q_prob_candidate, Mapping):
            for opt in option_keys:
                val = q_prob_candidate.get(opt)
                if val is None and opt.lower() in ("true", "false"):
                    val = q_prob_candidate.get(opt.lower() == "true")
                try:
                    num = float(val) if val is not None and not isinstance(val, bool) else 0.0
                except (TypeError, ValueError):
                    num = 0.0
                dist[opt] = max(0.0, num) if math.isfinite(num) else 0.0

        total = sum(dist.values())
        if total > 0:
            dist = {opt: round(v / total, 6) for opt, v in dist.items()}
        else:
            chosen = raw_answers_map.get(q_id)
            if chosen is None and not isinstance(parsed_output.get(q_id), Mapping):
                chosen = parsed_output.get(q_id)
            chosen_str = None
            if isinstance(chosen, bool):
                chosen_str = "true" if chosen else "false"
            elif chosen is not None:
                chosen_str = str(chosen).strip()

            matched_opt = None
            if chosen_str:
                for opt in option_keys:
                    if opt == chosen_str or opt.lower() == chosen_str.lower():
                        matched_opt = opt
                        break

            n = len(option_keys)
            if matched_opt is not None:
                if n == 1:
                    dist = {matched_opt: 1.0}
                else:
                    hi = 0.84
                    lo = round((1.0 - hi) / (n - 1), 6)
                    dist = {opt: (hi if opt == matched_opt else lo) for opt in option_keys}
            else:
                uni = round(1.0 / n, 6)
                dist = {opt: uni for opt in option_keys}

        probabilities[q_id] = dist
        best_opt = max(dist, key=lambda k: dist[k])
        if q_type == "noul":
            answers[q_id] = float(dist.get("true", 0.0)) >= float(dist.get("false", 0.0))
        elif q_type == "score":
            try:
                answers[q_id] = round(sum(float(k) * float(v) for k, v in dist.items()), 3)
            except ValueError:
                answers[q_id] = best_opt
        else:
            answers[q_id] = best_opt

    return probabilities, answers


def _build_system_one_messages(payload: Mapping[str, Any]) -> list[dict[str, str]]:
    """Build compact JSON-constrained messages for a System One decision request."""
    state = payload.get("state") if isinstance(payload.get("state"), Mapping) else {}
    raw_questions = payload.get("questions") if isinstance(payload.get("questions"), Sequence) else []
    compact_questions: list[dict[str, Any]] = []
    for q in raw_questions:
        if not isinstance(q, Mapping):
            continue
        q_id = str(q.get("id") or "").strip()
        if not q_id:
            continue
        q_type = str(q.get("type") or "choice").strip().lower()
        opt_keys, opt_descs = _normalize_question_options(q.get("options"), q_type)
        q_entry: dict[str, Any] = {
            "id": q_id,
            "type": q_type,
            "question": str(q.get("question") or ""),
            "options": opt_descs if opt_descs else opt_keys,
        }
        compact_questions.append(q_entry)

    system_prompt = (
        "You are a Jev / System One typed decision engine (`choice`, `score`, `noul`). "
        "Respond with ONLY a valid JSON object containing key \"answers\" mapping each question id "
        "to its single best option string from that question's options, and optional key \"probabilities\" "
        "mapping each question id to a probability distribution over its options."
    )
    user_payload = {
        "state": dict(state),
        "questions": compact_questions,
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def _complete_ollama_system_one(
    upstream_url: str,
    ollama_model: str,
    messages: Sequence[Mapping[str, Any]],
    *,
    temperature: float = 0.2,
    timeout_seconds: float = 6.0,
) -> CompletionResponse:
    """Invoke local Ollama `/api/chat` with `think: false` and `format: json` for fast System One scoring."""
    url = f"{upstream_url.rstrip('/')}/api/chat"
    body_payload = {
        "model": ollama_model,
        "messages": [dict(m) for m in messages],
        "stream": False,
        "think": False,
        "format": "json",
        "options": {
            "temperature": max(0.0, float(temperature)),
            "num_predict": 256,
        },
    }
    req = Request(
        url,
        data=json.dumps(body_payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "subllm-proxy"},
        method="POST",
    )
    with urlopen(req, timeout=timeout_seconds) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    msg = data.get("message") if isinstance(data, Mapping) else {}
    content = str(msg.get("content") or "") if isinstance(msg, Mapping) else ""
    prompt_tokens = int(data.get("prompt_eval_count") or 0) if isinstance(data, Mapping) else 0
    eval_tokens = int(data.get("eval_count") or 0) if isinstance(data, Mapping) else 0
    return CompletionResponse(
        content=content,
        provider="ollama",
        model=str(data.get("model") or ollama_model),
        usage={"input_tokens": prompt_tokens, "output_tokens": eval_tokens},
        finish_reason=str(data.get("done_reason") or "stop"),
    )


def _model_family(model_id: str) -> str:
    lower = model_id.lower()
    if "glm" in lower:
        return "glm"
    if "qwen" in lower:
        return "qwen"
    if "claude" in lower:
        return "claude"
    if "gpt" in lower or "sol" in lower or "terra" in lower or "luna" in lower:
        return "gpt"
    if "gemini" in lower:
        return "gemini"
    if "deepseek" in lower:
        return "deepseek"
    if "grok" in lower:
        return "grok"
    if "llama" in lower:
        return "llama"
    return "custom"


def is_upstream_ollama_alive(upstream_url: str = DEFAULT_OLLAMA_UPSTREAM, timeout: float = 0.5) -> bool:
    try:
        req = Request(f"{upstream_url.rstrip('/')}/api/tags", headers={"User-Agent": "subllm-proxy"})
        with urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


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


def list_proxy_models(
    upstream_url: str = DEFAULT_OLLAMA_UPSTREAM, include_upstream: bool = True, *, fresh: bool = False,
) -> list[dict[str, Any]]:
    """Return unified list of available models for OpenAI and Ollama formats."""
    models: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for model_id, spec in MODELS.items():
        if spec.forbidden:
            continue
        seen_ids.add(model_id)
        family = _model_family(model_id)
        models.append({
            "id": model_id,
            "name": f"{model_id}:latest",
            "model": f"{model_id}:latest",
            "family": family,
            "families": [family],
            "parameter_size": "32B",
            "source": "subllm",
            "vision": spec.vision,
        })

    # Add registered route aliases
    for (app, func) in ROUTES:
        alias = f"{app}/{func}"
        if alias not in seen_ids:
            seen_ids.add(alias)
            models.append({
                "id": alias,
                "name": f"{alias}:latest",
                "model": f"{alias}:latest",
                "family": "custom",
                "families": ["custom"],
                "parameter_size": "32B",
                "source": "subllm-route",
                "vision": False,
            })

    if include_upstream:
        upstream_models = (get_upstream_ollama_models(upstream_url, fresh=True) if fresh
                           else get_upstream_ollama_models(upstream_url))
        for m in upstream_models:
            name = m.get("name") or m.get("model") or ""
            base_name = name.split(":")[0] if ":" in name else name
            if name and name not in seen_ids and base_name not in seen_ids:
                seen_ids.add(name)
                details = m.get("details") or {}
                family = details.get("family") or _model_family(name)
                models.append({
                    "id": name,
                    "name": name,
                    "model": name,
                    "family": family,
                    "families": details.get("families", [family]),
                    "parameter_size": details.get("parameter_size", "unknown"),
                    "source": "ollama-upstream",
                    "vision": False,
                })

    return models


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
        provider_policy = (runtime_policy.providers.get(provider_id)
                           or runtime_policy.custom_providers.get(provider_id))
        if provider_policy is None or not provider_policy.enabled:
            continue

        api_key = (
            environment.get(provider_spec.api_key_env, "")
        )
        if provider_id == "ollama" and not api_key:
            api_key = "ollama"
        if provider_spec.transport in CLI_EXECUTABLES:
            if shutil.which(CLI_EXECUTABLES[provider_spec.transport], path=environment.get("PATH")) is None:
                continue
            api_key = ""
        elif provider_spec.api_key_env and not credential_is_valid(provider_id, api_key):
            continue

        headers: dict[str, str] = {}
        if provider_spec.attribution_headers:
            headers = {"HTTP-Referer": app_url, "X-OpenRouter-Title": app_name}

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
        return adaptive.execute(adaptive_policy, model_id, messages,
            build_routes=lambda model: _build_model_resolved_routes(model, application, function, environ=environ),
            invoke=_complete_route, timeout_seconds=timeout_seconds,
            response_format=response_format, request_id=request_id, environ=environ,
            minimum_class=adaptive_policy.get("routes", {}).get(f"{application}/{function}"))
    routes = _build_model_resolved_routes(model_id, application, function, environ=environ)
    if not routes:
        raise CompletionError(f"no available provider with valid credentials for model '{model_id}'")

    runtime_policy = load_policy_config(environ=environ)
    execution = runtime_policy.execution
    routes = order_by_health(routes) if execution.failover_enabled else routes[:1]
    if not routes:
        raise CompletionError(f"all providers cooling down for model '{model_id}'")

    started_at = time.monotonic()
    failed_providers: set[str] = set()
    last_error: Exception | None = None

    for route in routes:
        if route.provider in failed_providers:
            continue
        elapsed = time.monotonic() - started_at
        input_chars = sum(len(str(m.get("content", ""))) for m in messages if isinstance(m, Mapping))
        attempt_budget = resolve_attempt_timeout(
            route.provider,
            route.wire_model,
            environ=environ,
            default=execution.attempt_timeout_seconds,
            input_chars=input_chars,
        )
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            break
        attempt_timeout = min(remaining, attempt_budget)
        attempt_started = time.monotonic()
        safe_cwd = Path.home()
        try:
            cur = Path.cwd()
            if cur.exists():
                safe_cwd = cur
        except Exception:
            pass
        try:
            response = _complete_route(
                route,
                messages,
                timeout_seconds=attempt_timeout,
                request_id=request_id,
                response_format=response_format,
                cwd=safe_cwd,
            )
            duration = time.monotonic() - attempt_started
            record_success(route.provider, latency_seconds=duration, policy=execution)
            return response
        except _RetryableAttemptError as exc:
            duration = time.monotonic() - attempt_started
            if exc.provider_level:
                record_failure(route.provider, reason=exc.outcome, latency_seconds=duration, policy=execution)
                failed_providers.add(route.provider)
            last_error = exc
            if not execution.failover_enabled:
                raise CompletionError(str(exc)) from exc
            continue

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


class SubLLMProxyHandler(BaseHTTPRequestHandler):
    ollama_upstream: str = DEFAULT_OLLAMA_UPSTREAM
    server_version = "subllm-proxy/1.0"

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, HEAD")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, Cache-Control, Pragma, X-Ticket, X-Subactor-Ticket, "
            "X-Application, X-Subactor-Application, X-Function, X-Subactor-Function, X-Request-ID",
        )
        self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self) -> None:
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

        parsed = urlparse(self.path)
        path = parsed.path

        if path in {"", "/", "/health"}:
            self._json(200, {
                "status": "ok",
                "service": "subllm-proxy",
                "version": "1.10.3",
                "upstream_ollama": is_upstream_ollama_alive(self.ollama_upstream),
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
            ollama_models = [
                {
                    "name": m["name"],
                    "model": m["model"],
                    "modified_at": now_iso,
                    "size": 32212254720,
                    "digest": f"sha256:subllm_{m['id'].replace('/', '_')}",
                    "details": {
                        "parent_model": "",
                        "format": "gguf",
                        "family": m["family"],
                        "families": m["families"],
                        "parameter_size": m["parameter_size"],
                        "quantization_level": "Q4_K_M",
                    },
                }
                for m in models
            ]
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

    def do_POST(self) -> None:
        if not self._local_host():
            self._error(421, "PROXY-001", "host is not a local bind")
            return

        parsed = urlparse(self.path)
        path = parsed.path
        payload = self._read_json()
        if payload is None:
            return

        if path in {"/v1/decide", "/v1/system-one/decide"}:
            self._handle_system_one_decide(payload)
            return

        if path == "/v1/chat/completions":
            self._handle_openai_chat_completions(payload)
            return

        if path == "/api/chat":
            self._handle_ollama_chat(payload)
            return

        if path == "/api/generate":
            self._handle_ollama_generate(payload)
            return

        if path == "/api/show":
            self._handle_ollama_show(payload)
            return

        # Upstream Ollama forward fallback
        if is_upstream_ollama_alive(self.ollama_upstream):
            self._forward_upstream("POST", path, payload)
            return

        self._error(404, "PROXY-404", f"path '{path}' is not registered")

    def _handle_system_one_decide(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            self._error(400, "INVALID_REQUEST", "JSON object payload is required")
            return
        questions = payload.get("questions")
        if not isinstance(questions, Sequence) or isinstance(questions, (str, bytes)) or not questions:
            self._error(400, "INVALID_REQUEST", "questions array is required")
            return
        valid_questions = [q for q in questions if isinstance(q, Mapping) and str(q.get("id") or "").strip()]
        if not valid_questions:
            self._error(400, "INVALID_REQUEST", "at least one valid question with id is required")
            return

        raw_model = str(payload.get("model") or "qwen3.5:0.8b")
        clean_model, ticket = _extract_ticket(raw_model, self.headers, payload)
        requested_timeout = payload.get("timeout")
        try:
            timeout = 8.0 if requested_timeout is None else float(requested_timeout)
            if isinstance(requested_timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("invalid timeout")
        except (TypeError, ValueError):
            self._error(400, "INVALID_REQUEST", "timeout must be finite and greater than zero")
            return

        try:
            temperature = float(payload.get("temperature", 0.2))
            if not math.isfinite(temperature):
                temperature = 0.2
        except (TypeError, ValueError):
            temperature = 0.2

        app = self.headers.get("X-Subactor-Application") or self.headers.get("X-Application") or "heyasa"
        func = self.headers.get("X-Subactor-Function") or self.headers.get("X-Function") or "command"
        req_id = f"sysone-{uuid.uuid4().hex[:12]}"
        messages = _build_system_one_messages(payload)

        t0 = time.monotonic()
        response: CompletionResponse | None = None
        last_error: Exception | None = None

        effective_upstream = _resolve_system_one_ollama_upstream(self.ollama_upstream)
        prefers_explicit_route = (
            (clean_model in MODELS and not clean_model.startswith("qwen"))
            or ("/" in clean_model and tuple(clean_model.split("/", 1)) in ROUTES)
        )
        if not prefers_explicit_route and is_upstream_ollama_alive(effective_upstream):
            local_model = _select_local_system_one_ollama_model(clean_model, effective_upstream)
            if local_model is not None:
                try:
                    response = _complete_ollama_system_one(
                        effective_upstream,
                        local_model,
                        messages,
                        temperature=temperature,
                        timeout_seconds=min(timeout, 6.0),
                    )
                except Exception as exc:
                    last_error = exc

        if response is None:
            fallback_payload = dict(payload)
            fallback_payload.setdefault("response_format", {"type": "json_object"})
            is_known_target = clean_model in MODELS or (
                "/" in clean_model and tuple(clean_model.split("/", 1)) in ROUTES
            )
            fallback_model = clean_model if is_known_target else f"{app}/{func}"
            try:
                response = self._execute_model_or_route(
                    fallback_model,
                    messages,
                    app,
                    func,
                    timeout,
                    req_id,
                    fallback_payload,
                )
            except Exception as exc:
                last_error = exc
                self._error(500, "COMPLETION_FAILED", str(last_error))
                return

        duration_ms = round((time.monotonic() - t0) * 1000)
        _write_proxy_receipt(ticket, app, func, clean_model, response, duration_ms)

        parsed = _extract_json_object(response.content)
        probabilities, answers = _normalize_system_one_probabilities(valid_questions, parsed)

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

    def _handle_openai_chat_completions(self, payload: Mapping[str, Any]) -> None:
        raw_model = str(payload.get("model") or "glm-5.3")
        clean_model, ticket = _extract_ticket(raw_model, self.headers, payload)
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            self._error(400, "INVALID_REQUEST", "messages array is required")
            return

        stream = bool(payload.get("stream", False))
        requested_timeout = payload.get("timeout")
        try:
            timeout = (load_policy_config().execution.attempt_timeout_seconds
                       if requested_timeout is None else float(requested_timeout))
            if isinstance(requested_timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
                raise ValueError("invalid timeout")
        except (TypeError, ValueError):
            self._error(400, "INVALID_REQUEST", "timeout must be finite and greater than zero")
            return
        req_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created_ts = int(time.time())

        # Determine application and function
        app = self.headers.get("X-Subactor-Application") or self.headers.get("X-Application")
        func = self.headers.get("X-Subactor-Function") or self.headers.get("X-Function")

        # Upstream Ollama forward fast-path for models not registered in SubLLM policy
        if (not adaptive.policy() and clean_model not in MODELS and "/" not in clean_model
                and is_upstream_ollama_alive(self.ollama_upstream)):
            self._forward_upstream("POST", "/v1/chat/completions", payload)
            return

        t0 = time.monotonic()
        try:
            response = self._execute_model_or_route(clean_model, messages, app, func, timeout, req_id, payload)
        except Exception as exc:
            if not adaptive.policy() and is_upstream_ollama_alive(self.ollama_upstream):
                self._forward_upstream("POST", "/v1/chat/completions", payload)
                return
            self._error(500, "COMPLETION_FAILED", str(exc))
            return

        duration_ms = round((time.monotonic() - t0) * 1000)
        _write_proxy_receipt(ticket, app or "subactor-proxy", func or "chat", clean_model, response, duration_ms)

        extra_headers = {
            "X-Subactor-Provider": response.provider,
            "X-Subactor-Model": response.model,
            "X-Subactor-Duration-Ms": str(duration_ms),
        }
        if ticket:
            extra_headers["X-Subactor-Ticket"] = ticket

        if stream:
            self.close_connection = True
            self.send_response(200)
            self._send_cors_headers()
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            for k, v in extra_headers.items():
                self.send_header(k, v)
            self.end_headers()

            # Stream text in chunks
            content = response.content
            chunk_size = 32
            for i in range(0, len(content), chunk_size):
                chunk_text = content[i : i + chunk_size]
                chunk_payload = {
                    "id": req_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": response.model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": (
                                {"role": "assistant", "content": chunk_text}
                                if i == 0
                                else {"content": chunk_text}
                            ),
                            "finish_reason": None,
                        }
                    ],
                }
                self.wfile.write(f"data: {json.dumps(chunk_payload)}\n\n".encode())
                self.wfile.flush()

            # Final stop chunk
            stop_payload = {
                "id": req_id,
                "object": "chat.completion.chunk",
                "created": created_ts,
                "model": response.model,
                "choices": [{"index": 0, "delta": {}, "finish_reason": response.finish_reason or "stop"}],
            }
            self.wfile.write(f"data: {json.dumps(stop_payload)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
            return

        result = {
            "id": req_id,
            "object": "chat.completion",
            "created": created_ts,
            "model": response.model,
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response.content,
                    },
                    "finish_reason": response.finish_reason or "stop",
                }
            ],
            "usage": {
                "prompt_tokens": response.usage.get("input_tokens", response.usage.get("prompt_tokens", 0)),
                "completion_tokens": response.usage.get("output_tokens", response.usage.get("completion_tokens", 0)),
                "total_tokens": (
                    response.usage.get("input_tokens", response.usage.get("prompt_tokens", 0))
                    + response.usage.get("output_tokens", response.usage.get("completion_tokens", 0))
                ),
            },
        }
        self._json(200, result, extra_headers=extra_headers)

    def _handle_ollama_chat(self, payload: Mapping[str, Any]) -> None:
        raw_model = str(payload.get("model") or "glm-5.3")
        clean_model, ticket = _extract_ticket(raw_model, self.headers, payload)
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            self._error(400, "INVALID_REQUEST", "messages array is required")
            return

        # Ollama defaults to stream: true unless stream: false is explicitly sent
        stream = payload.get("stream", True)
        timeout = 60.0
        now_iso = datetime.datetime.now(datetime.UTC).isoformat()

        app = self.headers.get("X-Subactor-Application") or self.headers.get("X-Application")
        func = self.headers.get("X-Subactor-Function") or self.headers.get("X-Function")

        # Upstream Ollama forward fast-path for models not registered in SubLLM policy
        if (not adaptive.policy() and clean_model not in MODELS and "/" not in clean_model
                and is_upstream_ollama_alive(self.ollama_upstream)):
            self._forward_upstream("POST", "/api/chat", payload)
            return

        t0 = time.monotonic()
        try:
            response = self._execute_model_or_route(clean_model, messages, app, func, timeout, None, payload)
        except Exception as exc:
            if not adaptive.policy() and is_upstream_ollama_alive(self.ollama_upstream):
                self._forward_upstream("POST", "/api/chat", payload)
                return
            self._error(500, "COMPLETION_FAILED", str(exc))
            return

        duration_ms = round((time.monotonic() - t0) * 1000)
        total_ns = duration_ms * 1_000_000
        _write_proxy_receipt(ticket, app or "subactor-proxy", func or "chat", clean_model, response, duration_ms)

        prompt_tokens = response.usage.get("input_tokens", response.usage.get("prompt_tokens", 0))
        eval_tokens = response.usage.get("output_tokens", response.usage.get("completion_tokens", 0))

        extra_headers = {
            "X-Subactor-Provider": response.provider,
            "X-Subactor-Model": response.model,
            "X-Subactor-Duration-Ms": str(duration_ms),
        }
        if ticket:
            extra_headers["X-Subactor-Ticket"] = ticket

        if stream:
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
                chunk_text = content[i : i + chunk_size]
                chunk_line = {
                    "model": response.model,
                    "created_at": now_iso,
                    "message": {"role": "assistant", "content": chunk_text},
                    "done": False,
                }
                self.wfile.write((json.dumps(chunk_line) + "\n").encode("utf-8"))
                self.wfile.flush()

            done_line = {
                "model": response.model,
                "created_at": now_iso,
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "total_duration": total_ns,
                "load_duration": 1_000_000,
                "prompt_eval_count": prompt_tokens,
                "eval_count": eval_tokens,
            }
            self.wfile.write((json.dumps(done_line) + "\n").encode("utf-8"))
            self.wfile.flush()
            return

        self._json(
            200,
            {
                "model": response.model,
                "created_at": now_iso,
                "message": {
                    "role": "assistant",
                    "content": response.content,
                },
                "done": True,
                "total_duration": total_ns,
                "load_duration": 1_000_000,
                "prompt_eval_count": prompt_tokens,
                "eval_count": eval_tokens,
            },
            extra_headers=extra_headers,
        )

    def _handle_ollama_generate(self, payload: Mapping[str, Any]) -> None:
        raw_model = str(payload.get("model") or "glm-5.3")
        clean_model, ticket = _extract_ticket(raw_model, self.headers, payload)
        prompt = str(payload.get("prompt") or "")
        system = str(payload.get("system") or "")
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt or " "})

        stream = payload.get("stream", True)
        timeout = 60.0
        now_iso = datetime.datetime.now(datetime.UTC).isoformat()

        app = self.headers.get("X-Subactor-Application") or self.headers.get("X-Application")
        func = self.headers.get("X-Subactor-Function") or self.headers.get("X-Function")

        # Upstream Ollama forward fast-path for models not registered in SubLLM policy
        if (not adaptive.policy() and clean_model not in MODELS and "/" not in clean_model
                and is_upstream_ollama_alive(self.ollama_upstream)):
            self._forward_upstream("POST", "/api/generate", payload)
            return

        t0 = time.monotonic()
        try:
            response = self._execute_model_or_route(clean_model, messages, app, func, timeout, None, payload)
        except Exception as exc:
            if not adaptive.policy() and is_upstream_ollama_alive(self.ollama_upstream):
                self._forward_upstream("POST", "/api/generate", payload)
                return
            self._error(500, "COMPLETION_FAILED", str(exc))
            return

        duration_ms = round((time.monotonic() - t0) * 1000)
        total_ns = duration_ms * 1_000_000
        _write_proxy_receipt(ticket, app or "subactor-proxy", func or "chat", clean_model, response, duration_ms)

        prompt_tokens = response.usage.get("input_tokens", response.usage.get("prompt_tokens", 0))
        eval_tokens = response.usage.get("output_tokens", response.usage.get("completion_tokens", 0))

        extra_headers = {
            "X-Subactor-Provider": response.provider,
            "X-Subactor-Model": response.model,
            "X-Subactor-Duration-Ms": str(duration_ms),
        }
        if ticket:
            extra_headers["X-Subactor-Ticket"] = ticket

        if stream:
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
                chunk_text = content[i : i + chunk_size]
                chunk_line = {
                    "model": response.model,
                    "created_at": now_iso,
                    "response": chunk_text,
                    "done": False,
                }
                self.wfile.write((json.dumps(chunk_line) + "\n").encode("utf-8"))
                self.wfile.flush()

            done_line = {
                "model": response.model,
                "created_at": now_iso,
                "response": "",
                "done": True,
                "total_duration": total_ns,
                "load_duration": 1_000_000,
                "prompt_eval_count": prompt_tokens,
                "eval_count": eval_tokens,
            }
            self.wfile.write((json.dumps(done_line) + "\n").encode("utf-8"))
            self.wfile.flush()
            return

        self._json(
            200,
            {
                "model": response.model,
                "created_at": now_iso,
                "response": response.content,
                "done": True,
                "total_duration": total_ns,
                "load_duration": 1_000_000,
                "prompt_eval_count": prompt_tokens,
                "eval_count": eval_tokens,
            },
            extra_headers=extra_headers,
        )

    def _handle_ollama_show(self, payload: Mapping[str, Any]) -> None:
        name = str(payload.get("name") or payload.get("model") or "glm-5.3")
        base = name.split(":")[0]
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
                "parameter_size": "32B",
                "quantization_level": "Q4_K_M",
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
        try:
            with urlopen(req, timeout=120) as resp:
                body = resp.read()
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
            self.send_response(exc.code)
            self._send_cors_headers()
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except URLError as exc:
            self._error(502, "UPSTREAM_UNAVAILABLE", f"failed to connect to upstream Ollama: {exc.reason}")

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
