"""Opt-in Cline CLI transport using the operator's local login and subscriptions.

Uses the local Cline CLI (e.g. ClinePass deepseek-v4.1-flash-1017) in headless
JSON mode with plan mode (-p) enabled for fast, safe text completions.
No file edits or unauthorized terminal execution is performed.
"""
from __future__ import annotations

import json
import math
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .cli_common import MAX_BYTES, private_root, render_prompt, response_mode, run_cli, token_usage
from .errors import CompletionError

_CODE = "SUBLLM-CLINE-CLI"
MAX_PROMPT_BYTES = 120_000
_USAGE_KEYS = {
    "input_tokens": ("inputTokens", "input_tokens", "totalInputTokens"),
    "output_tokens": ("outputTokens", "output_tokens", "totalOutputTokens"),
    "cached_input_tokens": ("cacheReadTokens", "cache_read_input_tokens", "totalCacheReadTokens"),
}


def _terminal_result(data: bytes) -> bool:
    """Cline CLI emits JSON events line-by-line and can stay open after final usage."""
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("type") == "done":
            return True
        ev = doc.get("event")
        if isinstance(ev, dict) and ev.get("type") in ("usage", "iteration_end"):
            return True
    return False


def _parse_cline_output(data: bytes) -> tuple[str, dict[str, Any]]:
    """Parse text and usage from cline --json output."""
    texts: list[str] = []
    usage_doc: dict[str, Any] | None = None
    for line in data.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            doc = json.loads(line)
        except (ValueError, UnicodeError):
            continue
        if not isinstance(doc, dict):
            continue
        if doc.get("type") == "done":
            if isinstance(doc.get("text"), str):
                texts.append(doc["text"])
            if isinstance(doc.get("usage"), dict):
                usage_doc = doc["usage"]
        ev = doc.get("event")
        if isinstance(ev, dict):
            ev_type = ev.get("type")
            if ev_type in ("content_start", "content_delta"):
                txt = ev.get("text")
                if isinstance(txt, str):
                    texts.append(txt)
            elif ev_type == "usage":
                usage_doc = ev

    content = "".join(texts).strip()
    usage = token_usage(usage_doc, _USAGE_KEYS)
    return content, usage


def invoke(
    model: str,
    messages: Sequence[Mapping[str, Any]],
    timeout_seconds: float,
    response_format: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise CompletionError("Cline CLI needs a finite positive timeout", diagnostic_code=f"{_CODE}-TIMEOUT")
    mode, _schema = response_mode(response_format, name="Cline CLI")
    if mode == "json_schema":
        raise CompletionError("Cline CLI does not support enforced JSON schemas",
                              diagnostic_code=f"{_CODE}-FORMAT")
    prompt = render_prompt(messages, json_object=mode == "json_object")
    if len(prompt.encode()) > MAX_PROMPT_BYTES or "\x00" in prompt:
        raise CompletionError("Cline CLI prompt exceeds argument budget or contains NUL",
                              diagnostic_code=f"{_CODE}-BUDGET")
    executable = shutil.which("cline")
    if executable is None:
        raise CompletionError("local Cline CLI executable unavailable", diagnostic_code=f"{_CODE}-UNAVAILABLE")

    with private_root("subllm-cline-") as directory:
        root = Path(directory)
        argv = [executable, "--json", "-p", "-m", model, prompt]
        data = run_cli(argv, stdin_bytes=None, timeout_seconds=timeout_seconds, root=root,
                       code_prefix=_CODE, label="Cline CLI", output_complete=_terminal_result)

    try:
        content, usage = _parse_cline_output(data)
        if not content:
            raise ValueError("empty answer")
        if mode == "json_object":
            lines = content.splitlines()
            if len(lines) >= 3 and lines[0] in ("```json", "```") and lines[-1] == "```":
                content = "\n".join(lines[1:-1]).strip()
            if not isinstance(json.loads(content), dict):
                raise ValueError("expected JSON object")
    except CompletionError:
        raise
    except (ValueError, UnicodeError) as exc:
        raise CompletionError("Cline CLI returned incomplete or invalid output",
                              diagnostic_code=f"{_CODE}-OUTPUT") from exc
    return content, usage
