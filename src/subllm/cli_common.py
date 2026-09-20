"""Shared hardened runner for CLI-authenticated transports (Claude Code, Antigravity agy).

Authentication stays inside the local CLI's own credential store: no API key is
copied into the child, no target checkout or arbitrary argv is accepted, and the
working root is a private empty directory. The directory is not a VM sandbox.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import CompletionError

MAX_BYTES = 1_000_000
# CLI-authenticated transports and the local executable each one needs.
CLI_EXECUTABLES = {"codex-cli": "codex", "claude-cli": "claude", "agy-cli": "agy"}
CLI_LOGIN_LABELS = {"codex-cli": "Codex", "claude-cli": "Claude Code", "agy-cli": "Antigravity"}
# Environment forwarded to the child. Credentials are deliberately absent; the
# CLI reads its own login through HOME.
ENVIRONMENT_ALLOWLIST = frozenset({
    "HOME", "PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT", "WINDIR",
    "SSL_CERT_FILE", "SSL_CERT_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME",
})
JSON_OBJECT_INSTRUCTION = (
    "Respond with a single valid JSON object and nothing else: no prose, no code fences."
)


def render_prompt(messages: Sequence[Mapping[str, Any]], *, json_object: bool = False) -> str:
    """Render chat messages as deterministic role-labelled text.

    Only text content is supported; a non-text part fails closed instead of
    being silently dropped.
    """
    blocks: list[str] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content", "")
        if isinstance(content, list):
            parts: list[str] = []
            for part in content:
                if not isinstance(part, Mapping) or part.get("type") != "text":
                    raise CompletionError("CLI transports accept text messages only",
                                          diagnostic_code="SUBLLM-CLI-UNSUPPORTED-CONTENT")
                parts.append(str(part.get("text", "")))
            content = "\n".join(parts)
        elif not isinstance(content, str):
            raise CompletionError("CLI transports accept text messages only",
                                  diagnostic_code="SUBLLM-CLI-UNSUPPORTED-CONTENT")
        blocks.append(f"[{role}]\n{content}")
    if json_object:
        blocks.append(f"[system]\n{JSON_OBJECT_INSTRUCTION}")
    return "\n\n".join(blocks)


def response_mode(response_format: Mapping[str, Any] | None, *, name: str) -> tuple[str, Mapping[str, Any] | None]:
    """Return ("text" | "json_object" | "json_schema", schema) or fail closed."""
    if response_format is None:
        return "text", None
    kind = response_format.get("type")
    if kind == "json_object":
        return "json_object", None
    if kind == "json_schema":
        schema = response_format.get("json_schema", {}).get("schema")
        if not isinstance(schema, Mapping):
            raise CompletionError(f"{name} response schema must be an object")
        return "json_schema", schema
    raise CompletionError(f"{name} supports text, json_object and json_schema response formats")


def child_environment(environ: Mapping[str, str] | None = None) -> dict[str, str]:
    source = os.environ if environ is None else environ
    return {key: value for key, value in source.items() if key in ENVIRONMENT_ALLOWLIST}


def run_cli(
    argv: Sequence[str],
    *,
    stdin_bytes: bytes | None,
    timeout_seconds: float,
    root: Path,
    code_prefix: str,
    label: str,
    max_bytes: int = MAX_BYTES,
) -> bytes:
    """Run one fixed CLI invocation and return bounded stdout.

    The child gets its own session so a timeout terminates the whole process
    group, including descendants that outlive the CLI itself.
    """
    from .client_workers import _terminate_worker_process_group

    stdout_path = root / "stdout.bin"
    stdin_path = root / "stdin.bin"
    with stdin_path.open("wb+") as stdin, stdout_path.open("wb") as stdout:
        if stdin_bytes:
            stdin.write(stdin_bytes)
            stdin.seek(0)
        process = subprocess.Popen(
            list(argv), stdin=stdin, stdout=stdout, stderr=subprocess.DEVNULL, cwd=root,
            env=child_environment(), start_new_session=True,
        )
        deadline = time.monotonic() + timeout_seconds
        try:
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise CompletionError(f"{label} attempt timed out", diagnostic_code=f"{code_prefix}-TIMEOUT")
                if stdout_path.stat().st_size > max_bytes:
                    raise CompletionError(f"{label} output exceeds byte budget",
                                          diagnostic_code=f"{code_prefix}-BUDGET")
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        finally:
            # Reap descendants even if the CLI exited before its children.
            _terminate_worker_process_group(process)
    if process.returncode != 0:
        raise CompletionError(f"{label} failed; check the local CLI login and model access",
                              diagnostic_code=f"{code_prefix}-FAILED")
    data = stdout_path.read_bytes()
    if len(data) > max_bytes:
        raise CompletionError(f"{label} output exceeds byte budget", diagnostic_code=f"{code_prefix}-BUDGET")
    return data


def private_root(prefix: str) -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(prefix=prefix)


def token_usage(raw: Any, keys: Mapping[str, Sequence[str]]) -> dict[str, int]:
    """Project provider usage onto subllm's usage keys, keeping non-negative ints only.

    keys maps an output key to the source keys summed into it.
    """
    if not isinstance(raw, Mapping):
        return {}
    usage: dict[str, int] = {}
    for target, sources in keys.items():
        values: list[int] = []
        valid = True
        for source in sources:
            if source not in raw:
                continue
            value = raw[source]
            if type(value) is int and value >= 0:
                values.append(value)
            else:
                valid = False
                break
        if valid and values:
            usage[target] = sum(values)
    return usage
