from __future__ import annotations

import datetime
import json
import re
import shutil
import time
import uuid
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .client_routes import _complete_route, complete
from .client_types import CompletionResponse, _RetryableAttemptError
from .credential_env import credential_is_valid, merged_environment
from .errors import CompletionError, SubLLMError
from .health import order_by_health, record_failure, record_success
from .policy import MODELS, PROVIDERS, ROUTES
from .policy_config import load_policy_config
from .types import ResolvedRoute

ALLOWED_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
DEFAULT_OLLAMA_UPSTREAM = "http://127.0.0.1:11434"
DEFAULT_PROXY_PORT = 11435

_TICKET_PATTERN = re.compile(r"^(ticket-[A-Za-z0-9_.-]+)")


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


def get_upstream_ollama_models(
    upstream_url: str = DEFAULT_OLLAMA_UPSTREAM, timeout: float = 0.8
) -> list[dict[str, Any]]:
    try:
        req = Request(f"{upstream_url.rstrip('/')}/api/tags", headers={"User-Agent": "subllm-proxy"})
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("models", []) if isinstance(data, dict) else []
    except Exception:
        return []


def list_proxy_models(
    upstream_url: str = DEFAULT_OLLAMA_UPSTREAM, include_upstream: bool = True
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
        upstream_models = get_upstream_ollama_models(upstream_url)
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
    runtime_policy = load_policy_config()
    model_spec = MODELS.get(model_id)
    if model_spec is None or model_spec.forbidden:
        return ()

    app_spec = runtime_policy.applications.get(application) or runtime_policy.applications.get("subactor-proxy")
    app_name = app_spec.name if app_spec else application
    app_url = app_spec.url if app_spec else "https://github.com/subactor/subllm"

    candidates: list[ResolvedRoute] = []
    for provider_id, provider_model in model_spec.providers.items():
        provider_spec = PROVIDERS.get(provider_id)
        if not provider_spec:
            continue
        provider_policy = runtime_policy.providers.get(provider_id)
        if provider_policy and not provider_policy.enabled:
            continue

        api_key = environment.get(provider_spec.api_key_env, "")
        if provider_spec.transport == "codex-cli":
            if shutil.which("codex", path=environment.get("PATH")) is None:
                continue
            api_key = ""
        elif not credential_is_valid(provider_id, api_key):
            continue

        headers: dict[str, str] = {}
        if provider_spec.attribution_headers:
            headers = {"HTTP-Referer": app_url, "X-OpenRouter-Title": app_name}

        priority = (provider_policy.priority if provider_policy else 50)

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
                model_parameters={},
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
        remaining = timeout_seconds - elapsed
        if remaining <= 0:
            break
        attempt_timeout = min(remaining, execution.attempt_timeout_seconds) if execution.failover_enabled else remaining
        attempt_started = time.monotonic()
        try:
            response = _complete_route(
                route,
                messages,
                timeout_seconds=attempt_timeout,
                request_id=request_id,
                response_format=response_format,
                cwd=Path.cwd(),
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
            "Authorization, Content-Type, X-Ticket, X-Subactor-Ticket, "
            "X-Application, X-Subactor-Application, X-Function, X-Subactor-Function, X-Request-ID",
        )
        self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

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
            models = list_proxy_models(self.ollama_upstream)
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
            models = list_proxy_models(self.ollama_upstream)
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

    def _handle_openai_chat_completions(self, payload: Mapping[str, Any]) -> None:
        raw_model = str(payload.get("model") or "glm-5.3")
        clean_model, ticket = _extract_ticket(raw_model, self.headers, payload)
        messages = payload.get("messages")
        if not isinstance(messages, list) or not messages:
            self._error(400, "INVALID_REQUEST", "messages array is required")
            return

        stream = bool(payload.get("stream", False))
        timeout = float(payload.get("timeout") or 60.0)
        req_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        created_ts = int(time.time())

        # Determine application and function
        app = self.headers.get("X-Subactor-Application") or self.headers.get("X-Application")
        func = self.headers.get("X-Subactor-Function") or self.headers.get("X-Function")

        t0 = time.monotonic()
        try:
            response = self._execute_model_or_route(clean_model, messages, app, func, timeout, req_id, payload)
        except Exception as exc:
            # Check upstream fallback if model unknown to subllm
            if clean_model not in MODELS and "/" not in clean_model and is_upstream_ollama_alive(self.ollama_upstream):
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
                    "model": clean_model,
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
                "model": clean_model,
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
            "model": clean_model,
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

        t0 = time.monotonic()
        try:
            response = self._execute_model_or_route(clean_model, messages, app, func, timeout, None, payload)
        except Exception as exc:
            if clean_model not in MODELS and "/" not in clean_model and is_upstream_ollama_alive(self.ollama_upstream):
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
                    "model": clean_model,
                    "created_at": now_iso,
                    "message": {"role": "assistant", "content": chunk_text},
                    "done": False,
                }
                self.wfile.write((json.dumps(chunk_line) + "\n").encode("utf-8"))
                self.wfile.flush()

            done_line = {
                "model": clean_model,
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
                "model": clean_model,
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

        t0 = time.monotonic()
        try:
            response = self._execute_model_or_route(clean_model, messages, app, func, timeout, None, payload)
        except Exception as exc:
            if clean_model not in MODELS and "/" not in clean_model and is_upstream_ollama_alive(self.ollama_upstream):
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
                    "model": clean_model,
                    "created_at": now_iso,
                    "response": chunk_text,
                    "done": False,
                }
                self.wfile.write((json.dumps(chunk_line) + "\n").encode("utf-8"))
                self.wfile.flush()

            done_line = {
                "model": clean_model,
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
                "model": clean_model,
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
        # 1. Direct application/function notation e.g. "koru-agent/queue-executor"
        if "/" in clean_model:
            target_app, target_func = clean_model.split("/", 1)
            return complete(target_app, target_func, messages, timeout_seconds=timeout, request_id=req_id)

        # 2. If app and func specified from headers and exists in ROUTES
        if app and func and (app, func) in ROUTES:
            return complete(app, func, messages, timeout_seconds=timeout, request_id=req_id)

        # 3. Model is a known catalog model in MODELS
        if clean_model in MODELS:
            return _complete_model_direct(
                clean_model,
                messages,
                application=app or "subactor-proxy",
                function=func or "chat",
                timeout_seconds=timeout,
                request_id=req_id,
            )

        # 4. Fallback to default subactor-proxy/chat
        return complete("subactor-proxy", "chat", messages, timeout_seconds=timeout, request_id=req_id)

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
