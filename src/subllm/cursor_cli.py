"""Opt-in Cursor CLI transport using the operator's local login.

Auto is a routing mode, not a named model or a quality/cost guarantee. Execution
uses a private workspace, ask mode and explicit tool denials. The workspace is
not an OS sandbox. SDK credentials and paid-plan fallback are never injected.
"""
from __future__ import annotations

import json
import math
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .cli_common import private_root, render_prompt, response_mode, run_cli, token_usage
from .errors import CompletionError

_CODE = "SUBLLM-CURSOR-CLI"
MAX_PROMPT_BYTES = 120_000
_DENIED_TOOLS = ["Shell(*)", "Read(**)", "Read(/**)", "Write(**)", "Write(/**)", "WebFetch(*)", "Mcp(*:*)"]
_USAGE_KEYS = {
    "input_tokens": ("input_tokens",),
    "output_tokens": ("output_tokens",),
    "cached_input_tokens": ("cache_read_input_tokens",),
}


def _terminal_result(data: bytes) -> bool:
    """Cursor can keep running after emitting its terminal JSON result."""
    try:
        result = json.loads(data)
    except (ValueError, UnicodeError):
        return False
    return isinstance(result, dict) and result.get("type") == "result"


def invoke(
    model: str,
    messages: Sequence[Mapping[str, Any]],
    timeout_seconds: float,
    response_format: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    if model != "auto":
        raise CompletionError("Cursor CLI transport currently supports only explicit Auto routing",
                              diagnostic_code=f"{_CODE}-MODEL")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise CompletionError("Cursor CLI needs a finite positive timeout", diagnostic_code=f"{_CODE}-TIMEOUT")
    mode, _schema = response_mode(response_format, name="Cursor CLI")
    if mode == "json_schema":
        raise CompletionError("Cursor CLI does not support enforced JSON schemas",
                              diagnostic_code=f"{_CODE}-FORMAT")
    prompt = render_prompt(messages, json_object=mode == "json_object")
    if len(prompt.encode()) > MAX_PROMPT_BYTES or "\x00" in prompt:
        raise CompletionError("Cursor CLI prompt exceeds argument budget or contains NUL",
                              diagnostic_code=f"{_CODE}-BUDGET")
    executable = shutil.which("cursor-agent")
    if executable is None:
        raise CompletionError("local Cursor CLI executable unavailable", diagnostic_code=f"{_CODE}-UNAVAILABLE")
    with private_root("subllm-cursor-") as directory:
        root = Path(directory)
        config = root / ".cursor" / "cli.json"
        config.parent.mkdir(mode=0o700)
        config.write_text(json.dumps({"permissions": {"allow": [], "deny": _DENIED_TOOLS}}), encoding="utf-8")
        config.chmod(0o600)
        argv = [executable, "--print", "--trust", "--mode", "ask", "--model", model,
                "--output-format", "json", "--workspace", str(root), prompt]
        data = run_cli(argv, stdin_bytes=None, timeout_seconds=timeout_seconds, root=root,
                       code_prefix=_CODE, label="Cursor CLI", output_complete=_terminal_result)
    try:
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("unexpected envelope")
        if result.get("type") != "result" or result.get("subtype") != "success" or result.get("is_error") is not False:
            raise CompletionError("Cursor CLI reported failure; check local login and model access",
                                  diagnostic_code=f"{_CODE}-FAILED")
        content = result.get("result")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty answer")
        content = content.strip()
        if mode == "json_object":
            # CLI sometimes wraps JSON in one Markdown fence despite the prompt.
            lines = content.splitlines()
            if len(lines) >= 3 and lines[0] in ("```json", "```") and lines[-1] == "```":
                content = "\n".join(lines[1:-1]).strip()
            if not isinstance(json.loads(content), dict):
                raise ValueError("expected JSON object")
        usage = token_usage(result.get("usage"), _USAGE_KEYS)
    except CompletionError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise CompletionError("Cursor CLI returned incomplete or invalid output",
                              diagnostic_code=f"{_CODE}-OUTPUT") from exc
    return content, usage
