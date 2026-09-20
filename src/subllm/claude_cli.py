"""Fixed Claude Code print-mode transport. Authentication remains inside the local CLI.

Uses the operator's Claude Code login (subscription) instead of ANTHROPIC_API_KEY.
No tool, slash command, settings file, session persistence or MCP server is
enabled; the working root is a private empty directory.
"""
from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .cli_common import (
    MAX_BYTES,
    private_root,
    render_prompt,
    response_mode,
    run_cli,
    token_usage,
)
from .errors import CompletionError

_CODE = "SUBLLM-CLAUDE"
_USAGE_KEYS = {
    "input_tokens": ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"),
    "output_tokens": ("output_tokens",),
    "cached_input_tokens": ("cache_read_input_tokens",),
}


def invoke(
    model: str,
    messages: Sequence[Mapping[str, Any]],
    timeout_seconds: float,
    response_format: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    executable = shutil.which("claude")
    if executable is None:
        raise CompletionError("local Claude Code executable unavailable",
                              diagnostic_code=f"{_CODE}-UNAVAILABLE")
    mode, schema = response_mode(response_format, name="Claude")
    prompt = render_prompt(messages, json_object=mode == "json_object").encode()
    if len(prompt) > MAX_BYTES:
        raise CompletionError("Claude prompt exceeds byte budget", diagnostic_code=f"{_CODE}-BUDGET")
    with private_root("subllm-claude-") as directory:
        root = Path(directory)
        argv = [executable, "-p", "--output-format", "json", "--model", model,
                "--no-session-persistence", "--tools", "", "--disable-slash-commands",
                "--setting-sources", ""]
        if mode == "json_schema":
            argv += ["--json-schema", json.dumps(schema, separators=(",", ":"))]
        data = run_cli(argv, stdin_bytes=prompt, timeout_seconds=timeout_seconds, root=root,
                       code_prefix=_CODE, label="Claude")
    try:
        result = json.loads(data)
        if not isinstance(result, dict) or result.get("type") != "result":
            raise ValueError("unexpected envelope")
        if result.get("is_error") or result.get("subtype") != "success":
            status = result.get("api_error_status")
            raise CompletionError(
                "Claude reported an error; check the local CLI login and model access",
                diagnostic_code=f"{_CODE}-HTTP-{status}" if type(status) is int else f"{_CODE}-FAILED",
            )
        content = result.get("structured_output") if mode == "json_schema" and result.get(
            "structured_output") is not None else result.get("result")
        if isinstance(content, (dict, list)):
            content = json.dumps(content, ensure_ascii=False)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty answer")
        usage = token_usage(result.get("usage"), _USAGE_KEYS)
    except CompletionError:
        raise
    except (ValueError, AttributeError, UnicodeError) as exc:
        raise CompletionError("Claude returned incomplete or invalid output",
                              diagnostic_code=f"{_CODE}-OUTPUT") from exc
    return content.strip(), usage
