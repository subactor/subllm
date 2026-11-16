"""Request-scoped AI configuration shared by gateway consumers.

Applications store one private profile and send inference to OQLLM. Provider
credentials and native model adapters belong behind the gateway. A profile is
read once for each request; saving another revision never mutates that copy.
"""

from __future__ import annotations

import contextlib
import copy
import json
import math
import os
import stat
import tempfile
import threading
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

SCHEMA = "subllm.ai-runtime/v1"
PROFILE_FILENAME = "ai-runtime.json"
ROLES = ("llm", "stt", "tts", "decision")
ENDPOINTS = {
    "llm": "/v1/chat/completions",
    "stt": "/v1/speech/transcribe",
    "tts": "/v1/speech/synthesize",
    "decision": "/v1/decide",
}
MAX_PROFILE_BYTES = 65536
MAX_EXCHANGE_BYTES = 12 * 1024 * 1024
_RESERVED_PARAMETERS = frozenset(
    {
        "model",
        "messages",
        "state",
        "questions",
        "offline",
        "api_key",
        "headers",
        "authorization",
        "endpoint",
        "base_url",
        "url",
        "application",
        "function",
        "audio_base64",
        "text",
        "input",
        "stream",
    }
)
_LOCK = threading.RLock()
_REQUEST_PARAMETERS = ContextVar("subllm_request_model_parameters", default=None)

# Values are transport/model parameters, never application execution authority.
PARAMETERS = {
    "llm": {
        "protocol": ["openai", "ollama"],
        "temperature": [0, 2],
        "top_p": [0, 1],
        "top_k": [-1, 2048],
        "max_tokens": [1, 262144],
        "seed": [0, 4294967295],
        "presence_penalty": [-2, 2],
        "frequency_penalty": [-2, 2],
        "repeat_penalty": [0, 4],
        "context_size": [128, 1048576],
        "stop": "string-list",
        "timeout": [0.1, 600],
    },
    "stt": {
        "engine": ["faster-whisper", "openai"],
        "language": "string",
        "device": ["auto", "cpu", "cuda"],
        "compute_type": "string",
        "beam_size": [1, 20],
        "best_of": [1, 20],
        "temperature": [0, 1],
        "vad_filter": "boolean",
        "initial_prompt": "string",
        "condition_on_previous_text": "boolean",
        "cpu_threads": [1, 256],
        "backend_options": "object",
        "timeout": [0.1, 600],
    },
    "tts": {
        "engine": ["piper", "openai"],
        "language": "string",
        "voice": "string",
        "speaker": [0, 4096],
        "speed": [0.25, 4],
        "length_scale": [0.25, 4],
        "noise_scale": [0, 2],
        "noise_w": [0, 2],
        "sentence_silence": [0, 5],
        "format": ["wav"],
        "timeout": [0.1, 600],
    },
    "decision": {"timeout": [0.1, 300]},
}
_INTEGER_PARAMETERS = frozenset(
    {"top_k", "max_tokens", "seed", "context_size", "beam_size", "best_of", "cpu_threads", "speaker"}
)


class ProfileError(ValueError):
    """Invalid or conflicting local operator configuration."""


class GatewayError(RuntimeError):
    """An unconfirmed gateway request; no provider fallback was attempted."""

    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status


def default_profile():
    return {
        "schema": SCHEMA,
        "revision": 0,
        "enabled": False,
        "gateway": {"url": os.environ.get("OQLLM_URL", "http://127.0.0.1:11437"), "api_key": ""},
        "roles": {
            "llm": {"model": "szeptnik-one/voice-programming", "parameters": {}},
            "stt": {
                "model": os.environ.get("HEYASA_FASTER_WHISPER_MODEL")
                or os.environ.get("WILLMUX_WHISPER_MODEL")
                or "small",
                "parameters": {"engine": "faster-whisper", "compute_type": "int8"},
            },
            "tts": {
                "model": os.environ.get("HEYASA_PIPER_MODEL")
                or os.environ.get("WILLMUX_PIPER_MODEL")
                or "piper:default",
                "parameters": {"engine": "piper", "format": "wav"},
            },
            "decision": {"model": "d1:3b", "parameters": {}},
        },
    }


def profile_path(state_dir=None):
    explicit = os.environ.get("HEYASA_AI_CONFIG")
    if explicit:
        return Path(explicit).expanduser().absolute()
    state = state_dir or os.environ.get("HEYASA_STATE_DIR") or Path.home() / ".local/share/heyasa"
    return Path(state).expanduser().absolute() / PROFILE_FILENAME


def gateway_url(value):
    if not isinstance(value, str) or len(value) > 2048 or any(c.isspace() for c in value):
        raise ProfileError("Invalid OQLLM gateway URL")
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.port == 0
            or parsed.path not in {"", "/", "/v1", "/v1/"}
        ):
            raise ValueError
    except ValueError:
        raise ProfileError("Gateway must be an HTTP(S) origin without credentials") from None
    return value.rstrip("/").removesuffix("/v1")


def validate_parameters(role, values):
    if not isinstance(values, dict) or len(values) > 64:
        raise ProfileError("Model parameters must be a JSON object")
    if role not in PARAMETERS or set(values) & _RESERVED_PARAMETERS:
        raise ProfileError("Model parameters cannot redefine request or routing fields")
    for name, value in values.items():
        if name not in PARAMETERS[role]:
            raise ProfileError(f"Unsupported {role} parameter: {name}")
        rule = PARAMETERS[role][name]
        if isinstance(rule, list) and rule and type(rule[0]) in (int, float):
            valid = type(value) in (int, float) and math.isfinite(value) and rule[0] <= value <= rule[1]
            if name in _INTEGER_PARAMETERS:
                valid = valid and type(value) is int
        elif isinstance(rule, list):
            valid = isinstance(value, str) and value in rule
        elif rule == "boolean":
            valid = type(value) is bool
        elif rule == "string-list":
            valid = (
                isinstance(value, list)
                and len(value) <= 16
                and all(isinstance(v, str) and 0 < len(v) <= 1024 for v in value)
            )
        elif rule == "object":
            valid = (
                isinstance(value, dict) and len(value) <= 32 and not (set(value) & (_RESERVED_PARAMETERS | {"audio"}))
            )
            try:
                valid = valid and len(json.dumps(value, allow_nan=False).encode()) <= 16384
            except (TypeError, ValueError):
                valid = False
        else:
            valid = isinstance(value, str) and len(value) <= 8192 and "\x00" not in value
        if not valid:
            raise ProfileError(f"Invalid {role} parameter: {name}")
    return copy.deepcopy(values)


def validate_profile(value):
    if not isinstance(value, dict) or set(value) != {"schema", "revision", "enabled", "gateway", "roles"}:
        raise ProfileError("Invalid AI runtime profile fields")
    if (
        value["schema"] != SCHEMA
        or type(value["revision"]) is not int
        or value["revision"] < 0
        or type(value["enabled"]) is not bool
    ):
        raise ProfileError("Invalid AI runtime profile identity")
    gateway = value["gateway"]
    if not isinstance(gateway, dict) or set(gateway) != {"url", "api_key"}:
        raise ProfileError("Invalid gateway configuration")
    key = gateway["api_key"]
    if not isinstance(key, str) or len(key) > 4096 or any(ord(c) < 32 for c in key):
        raise ProfileError("Invalid gateway credential")
    if not isinstance(value["roles"], dict) or set(value["roles"]) != set(ROLES):
        raise ProfileError("All four AI roles must be configured")
    result = copy.deepcopy(value)
    result["gateway"]["url"] = gateway_url(gateway["url"])
    for role, config in result["roles"].items():
        if not isinstance(config, dict) or set(config) != {"model", "parameters"}:
            raise ProfileError(f"Invalid {role} configuration")
        model = config["model"]
        if not isinstance(model, str) or not model.strip() or len(model) > 2048 or any(ord(c) < 32 for c in model):
            raise ProfileError(f"Invalid {role} model")
        config["model"] = model.strip()
        config["parameters"] = validate_parameters(role, config["parameters"])
    if len(json.dumps(result).encode()) > MAX_PROFILE_BYTES:
        raise ProfileError("AI profile exceeds the size limit")
    return result


def public_profile(value):
    result = copy.deepcopy(value)
    key = result["gateway"].pop("api_key", "")
    result["gateway"]["keySet"] = bool(key)
    return result


def _safe_path(path):
    path = Path(path).absolute()
    if any(part.is_symlink() for part in (path, *path.parents)):
        raise ProfileError("AI profile paths cannot contain symlinks")
    return path


class ProfileStore:
    def __init__(self, path=None):
        self.path = _safe_path(path or profile_path())

    def load(self):
        _safe_path(self.path)
        try:
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return validate_profile(default_profile())
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_nlink != 1
                or (os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077))
            ):
                raise ProfileError("AI profile must be a private file owned by the application user")
            raw = stream.read(MAX_PROFILE_BYTES + 1)
        if len(raw) > MAX_PROFILE_BYTES:
            raise ProfileError("AI profile exceeds the size limit")
        try:
            value = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
        except (ValueError, UnicodeDecodeError):
            raise ProfileError("AI profile is not valid JSON") from None
        return validate_profile(value)

    @contextlib.contextmanager
    def _writer_lock(self):
        with _LOCK:
            _safe_path(self.path.parent).mkdir(mode=0o700, parents=True, exist_ok=True)
            lock_path = _safe_path(self.path.with_suffix(".lock"))
            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or (os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077))
                ):
                    raise ProfileError("Invalid AI profile writer lock")
                if os.name == "nt":
                    import msvcrt

                    os.write(fd, b"0")
                    os.lseek(fd, 0, 0)
                    msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                os.close(fd)

    def save(self, value, *, expected_revision):
        if type(expected_revision) is not int or expected_revision < 0:
            raise ProfileError("Expected profile revision is required")
        with self._writer_lock():
            current = self.load()
            if current["revision"] != expected_revision:
                raise ProfileError("AI profile revision conflict; reload settings")
            candidate = self._candidate(value, current, current["revision"] + 1)
            fd, temp_name = tempfile.mkstemp(prefix=".ai-runtime-", dir=self.path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as stream:
                    json.dump(candidate, stream, ensure_ascii=False, allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, self.path)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            return public_profile(candidate)

    @staticmethod
    def _candidate(value, current, revision):
        candidate = copy.deepcopy(value)
        if not isinstance(candidate, dict) or not isinstance(candidate.get("gateway"), dict):
            raise ProfileError("Invalid AI profile")
        gateway = candidate["gateway"]
        gateway.pop("keySet", None)
        if "api_key" not in gateway:
            same_gateway = gateway_url(gateway.get("url")) == current["gateway"]["url"]
            gateway["api_key"] = current["gateway"]["api_key"] if same_gateway else ""
        candidate["revision"] = revision
        return validate_profile(candidate)

    def preview(self, value):
        """Validate an unsaved candidate without exposing or migrating a key."""
        current = self.load()
        return self._candidate(value, current, current["revision"])


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        raise GatewayError("OQLLM redirects are forbidden")


class GatewayClient:
    def __init__(self, profile, *, application="heyasa"):
        self.profile = validate_profile(profile)
        if not self.profile["enabled"]:
            raise ProfileError("AI gateway profile is disabled")
        self.application = application

    def _request(self, path, *, payload=None, timeout=30, role="configuration"):
        gateway = self.profile["gateway"]
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode() if payload is not None else None
        if body is not None and len(body) > MAX_EXCHANGE_BYTES:
            raise ProfileError("AI request exceeds the size limit")
        headers = {
            "Content-Type": "application/json",
            "X-Subactor-Application": self.application,
            "X-Subactor-Function": role,
        }
        if gateway["api_key"]:
            headers["Authorization"] = "Bearer " + gateway["api_key"]
        request = Request(
            gateway["url"] + path, data=body, headers=headers, method="POST" if body is not None else "GET"
        )
        try:
            with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
                raw = response.read(MAX_EXCHANGE_BYTES + 1)
        except HTTPError as error:
            error.close()
            raise GatewayError("OQLLM inference was rejected", status=error.code) from None
        except (URLError, OSError, TimeoutError):
            raise GatewayError("OQLLM inference could not be confirmed") from None
        if len(raw) > MAX_EXCHANGE_BYTES:
            raise GatewayError("OQLLM response exceeds the size limit")
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise GatewayError("OQLLM returned invalid JSON") from None
        if not isinstance(result, dict) or result.get("error"):
            raise GatewayError("OQLLM returned an inference error")
        return result

    def infer(self, role, payload):
        if role not in ROLES or not isinstance(payload, dict):
            raise ProfileError("Invalid AI inference role or request")
        config = self.profile["roles"][role]
        parameters = dict(config["parameters"])
        timeout = parameters.pop("timeout", 120)
        if "timeout" in payload:
            budget = payload["timeout"]
            if type(budget) not in (int, float) or not math.isfinite(budget) or budget <= 0:
                raise ProfileError("Invalid caller inference deadline")
            timeout = min(timeout, budget)
        protocol = parameters.pop("protocol", "openai") if role == "llm" else None
        if role == "llm" and protocol == "ollama":
            names = {"max_tokens": "num_predict", "context_size": "num_ctx"}
            options = {names.get(name, name): value for name, value in parameters.items()}
            request = {
                "model": config["model"],
                "messages": payload.get("messages", []),
                "stream": False,
                "options": options,
                "timeout": timeout,
            }
            response_format = payload.get("response_format")
            if isinstance(response_format, dict):
                kind = response_format.get("type")
                if kind == "json_object":
                    request["format"] = "json"
                elif kind == "json_schema":
                    request["format"] = response_format.get("json_schema", {}).get("schema")
            result = self._request("/api/chat", payload=request, timeout=timeout, role=role)
            if not isinstance(result.get("message"), dict):
                raise GatewayError("OQLLM returned an invalid Ollama chat response")
            return {
                "model": result.get("model", config["model"]),
                "choices": [{"message": result["message"]}],
                "usage": {
                    "prompt_tokens": result.get("prompt_eval_count"),
                    "completion_tokens": result.get("eval_count"),
                },
            }
        if role == "llm" and set(parameters) & {"top_k", "context_size", "repeat_penalty"}:
            raise ProfileError("Use the Ollama protocol for native context/top-k/repetition controls")
        request = {**payload, **parameters, "model": config["model"]}
        if role == "llm":
            request["stream"] = False
        if role == "decision":
            request["offline"] = True
        request["timeout"] = timeout
        return self._request(ENDPOINTS[role], payload=request, timeout=timeout, role=role)

    def capabilities(self):
        return self._request("/v1/ai/capabilities")


def capabilities():
    return {
        "schema": "subllm.ai-capabilities/v1",
        "profile_schema": SCHEMA,
        "roles": {role: {"endpoint": ENDPOINTS[role], "parameters": copy.deepcopy(PARAMETERS[role])} for role in ROLES},
        "switching": "new-request-snapshot",
        "stream_migration": False,
    }


@contextlib.contextmanager
def request_parameter_scope(payload):
    """Bind validated HTTP sampling controls to canonical SDK invocations."""
    values = {
        name: payload[name] for name in PARAMETERS["llm"] if name in payload and name not in {"timeout", "protocol"}
    }
    values = validate_parameters("llm", values)
    if set(values) & {"top_k", "context_size", "repeat_penalty"}:
        raise ProfileError("Native context/top-k/repetition controls require the Ollama API")
    token = _REQUEST_PARAMETERS.set(values)
    try:
        yield
    finally:
        _REQUEST_PARAMETERS.reset(token)


def request_parameters_active():
    return bool(_REQUEST_PARAMETERS.get())


def ollama_parameter_scope(options):
    if not isinstance(options, dict):
        raise ProfileError("Ollama options must be a JSON object")
    aliases = {"num_predict": "max_tokens", "num_ctx": "context_size"}
    values = {aliases.get(name, name): value for name, value in options.items()}
    if set(values) - (set(PARAMETERS["llm"]) - {"protocol", "timeout"}):
        raise ProfileError("Unsupported options for a policy-routed model; use a native Ollama model")
    return request_parameter_scope(values)


def apply_request_parameters(route):
    values = _REQUEST_PARAMETERS.get()
    if not values:
        return route
    supported = (
        {"temperature", "top_p", "max_tokens", "seed", "presence_penalty", "frequency_penalty", "stop"}
        if route.transport == "openai-compatible"
        else {"temperature", "top_p", "max_tokens"}
        if route.transport in {"anthropic", "gemini-sdk"}
        else set()
    )
    if set(values) - supported:
        from .errors import CompletionError

        raise CompletionError(
            "Selected transport does not support the requested model parameters",
            diagnostic_code="SUBLLM-PARAMETERS-UNSUPPORTED",
        )
    parameters = {**route.model_parameters, **values}
    ceiling = route.model_parameters.get("max_tokens")
    if ceiling is not None and "max_tokens" in values:
        from .generation import token_limit

        parameters["max_tokens"] = min(token_limit(ceiling, legacy_string=True), values["max_tokens"])
    return replace(route, model_parameters=parameters)
