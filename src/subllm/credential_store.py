"""Manage the shared SubLLM credential file: describe, set/replace, unset and verify keys.

No function returns or logs a credential value. Writes are atomic, keep mode 0600, keep every other
line (comments included) and leave a timestamped backup. The file is validated by the same loader
the runtime uses, so a file this module writes is a file the runtime accepts.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .credential_env import (
    _validate_file,
    credential_is_valid,
    credential_names,
    find_env_file,
    load_env_file,
)
from .errors import CredentialFileError
from .native_http import _NoRedirect
from .policy import PROVIDERS, SUBLLM_PROVIDER_ORDER
from .provider_order import parse_provider_order

_ASSIGNMENT = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")
_UNSAFE_VALUE = re.compile(r"[\s\"'`$\\]")


@dataclass(frozen=True)
class CredentialState:
    variable: str
    providers: tuple[str, ...]
    state: str  # absent | empty | invalid | set
    length: int


@dataclass(frozen=True)
class VerifyResult:
    variable: str
    status: str  # ok | limited | invalid | unreachable | unsupported | missing
    detail: str


def resolve_target(explicit: Path | None = None, *, environ: Mapping[str, str] | None = None) -> Path:
    path = explicit or find_env_file(environ=environ)
    if path is None:
        raise CredentialFileError("no credential file found; create one with `subllm env template > .env` "
                                  "and `chmod 600 .env`, or pass --file")
    return path.absolute()


def variable_for(token: str) -> str:
    """Accept a provider id (agy) or a variable name (GEMINI_API_KEY)."""
    provider = PROVIDERS.get(token)
    if provider is not None:
        if not provider.api_key_env:
            raise CredentialFileError(f"provider {token} uses a local CLI login and has no key to store")
        return provider.api_key_env
    if token in credential_names():
        return token
    known = ", ".join(sorted({*credential_names(), *(n for n, p in PROVIDERS.items() if p.api_key_env)}))
    raise CredentialFileError(f"unknown provider or variable {token!r}; known: {known}")


def providers_for(variable: str) -> tuple[str, ...]:
    return tuple(name for name, spec in PROVIDERS.items() if spec.api_key_env == variable)


def describe(path: Path) -> list[CredentialState]:
    values = load_env_file(path)
    states: list[CredentialState] = []
    for variable in credential_names():
        providers = providers_for(variable)
        value = values.get(variable)
        if value is None:
            state = "absent"
        elif not value:
            state = "empty"
        elif all(credential_is_valid(p, value) for p in providers or ("",)):
            state = "set"
        else:
            state = "invalid"
        states.append(CredentialState(variable, providers, state, len(value or "")))
    return states


def _rewrite(path: Path, transform, *, create: bool = False) -> Path | None:
    if not path.exists():
        if not create:
            raise CredentialFileError(f"credential file does not exist: {path}")
        text, backup = "", None
    else:
        _validate_file(path)  # mode 0600, regular file, not a symlink
        load_env_file(path)  # refuse to edit a file the runtime would reject
        text = path.read_text(encoding="utf-8")
        backup = path.with_name(f"{path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
        backup.chmod(0o600)
    lines = transform(text.splitlines())
    handle, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write("\n".join(lines) + "\n")
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return backup


def _assign(lines: list[str], variable: str, value: str) -> list[str]:
    out: list[str] = []
    placed = False
    for line in lines:
        match = _ASSIGNMENT.match(line.strip())
        if match and match.group(1) == variable:
            if not placed:
                out.append(f"{variable}={value}")
                placed = True
            continue  # drop duplicates: the loader rejects them
        out.append(line)
    if not placed:
        out.append(f"{variable}={value}")
    return out


def set_value(path: Path, variable: str, value: str) -> Path | None:
    """Store or replace a credential; returns the backup path when the file already existed."""
    if variable not in credential_names():
        raise CredentialFileError(f"{variable} is not a credential variable")
    if not value or _UNSAFE_VALUE.search(value) or len(value) < 8:
        raise CredentialFileError("credential must be one token without whitespace or quotes (8+ characters)")
    for provider in providers_for(variable):
        if not credential_is_valid(provider, value):
            raise CredentialFileError(f"value is not a valid {provider} credential (placeholder or wrong format)")
    return _rewrite(path, lambda lines: _assign(lines, variable, value), create=True)


def unset_value(path: Path, variable: str) -> Path | None:
    if variable not in credential_names():
        raise CredentialFileError(f"{variable} is not a credential variable")
    return _rewrite(path, lambda lines: _assign(lines, variable, ""))


def current_order(path: Path) -> str:
    return load_env_file(path).get(SUBLLM_PROVIDER_ORDER, "")


def set_order(path: Path, order: str) -> Path | None:
    if order:
        parse_provider_order(order)  # unknown or duplicate ids fail closed
    return _rewrite(path, lambda lines: _assign(lines, SUBLLM_PROVIDER_ORDER, order), create=True)


# --- live verification ---------------------------------------------------------------------------

_ENDPOINTS: dict[str, tuple[str, dict[str, str]]] = {
    "agy": ("https://generativelanguage.googleapis.com/v1beta/models?pageSize=1", {"x-goog-api-key": "{key}"}),
    "codex": ("https://api.openai.com/v1/models", {"Authorization": "Bearer {key}"}),
    "claude": ("https://api.anthropic.com/v1/models?limit=1",
               {"x-api-key": "{key}", "anthropic-version": "2023-06-01"}),
    "openrouter": ("https://openrouter.ai/api/v1/key", {"Authorization": "Bearer {key}"}),
    "zai": ("https://api.z.ai/api/coding/paas/v4/models", {"Authorization": "Bearer {key}"}),
}


def verify_key(variable: str, value: str, *, timeout_seconds: float = 20.0) -> VerifyResult:
    """Ask the provider whether the key is accepted. Never returns the key or the response body."""
    providers = [p for p in providers_for(variable) if p in _ENDPOINTS]
    if not value:
        return VerifyResult(variable, "missing", "no value stored")
    if not providers:
        return VerifyResult(variable, "unsupported", "no HTTP check is defined for this provider")
    url, headers = _ENDPOINTS[providers[0]]
    request = urllib.request.Request(url, headers={k: v.replace("{key}", value) for k, v in headers.items()})
    try:
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout_seconds):  # noqa: S310
            return VerifyResult(variable, "ok", "accepted by the provider")
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            return VerifyResult(variable, "invalid", f"rejected by the provider (HTTP {exc.code})")
        if exc.code == 429:
            return VerifyResult(variable, "limited", "key is valid but the provider reports a quota or rate limit")
        if exc.code in {404, 405}:
            return VerifyResult(variable, "unsupported", f"check endpoint not available (HTTP {exc.code})")
        return VerifyResult(variable, "unreachable", f"provider answered HTTP {exc.code}")
    except (urllib.error.URLError, TimeoutError, OSError):
        return VerifyResult(variable, "unreachable", "network error")
