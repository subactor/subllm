"""Fixed Antigravity `agy` print-mode transport. Authentication remains inside the local CLI.

Reaches Gemini, Claude Sonnet/Opus and GPT-OSS models through the operator's
Antigravity login instead of GEMINI_API_KEY. The prompt is a `--print=` argument
(the CLI has no stdin prompt in plain print mode), so it is bounded below the
Linux single-argument limit. The terminal sandbox is enabled and no permission
bypass flag is ever passed; the working root is a private empty directory.
"""
from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .cli_common import private_root, render_prompt, response_mode, run_cli, token_usage
from .errors import CompletionError

_CODE = "SUBLLM-AGY"
# MAX_ARG_STRLEN is 131072 bytes on Linux; keep headroom for the flag prefix.
MAX_PROMPT_BYTES = 120_000
_USAGE_KEYS = {
    "input_tokens": ("input_tokens",),
    "output_tokens": ("output_tokens",),
    "cached_input_tokens": ("cache_read_tokens",),
}


def invoke(
    model: str,
    messages: Sequence[Mapping[str, Any]],
    timeout_seconds: float,
    response_format: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    executable = shutil.which("agy")
    if executable is None:
        raise CompletionError("local Antigravity executable unavailable",
                              diagnostic_code=f"{_CODE}-UNAVAILABLE")
    mode, schema = response_mode(response_format, name="Antigravity")
    prompt = render_prompt(messages, json_object=mode == "json_object")
    if len(prompt.encode()) > MAX_PROMPT_BYTES or "\x00" in prompt:
        raise CompletionError("Antigravity prompt exceeds the single-argument budget or contains NUL",
                              diagnostic_code=f"{_CODE}-BUDGET")
    with private_root("subllm-agy-") as directory:
        root = Path(directory)
        argv = [executable, "--output-format", "json", "--model", model, "--sandbox"]
        if mode == "json_schema":
            schema_path = root / "response.schema.json"
            schema_path.write_text(json.dumps(schema))
            argv += ["--json-schema", str(schema_path)]
        argv.append(f"--print={prompt}")
        data = run_cli(argv, stdin_bytes=None, timeout_seconds=timeout_seconds, root=root,
                       code_prefix=_CODE, label="Antigravity")
    try:
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("unexpected envelope")
        if result.get("status") != "SUCCESS":
            raise CompletionError("Antigravity reported an error; check the local CLI login and model access",
                                  diagnostic_code=f"{_CODE}-FAILED")
        content = result.get("response")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty answer")
        usage = token_usage(result.get("usage"), _USAGE_KEYS)
    except CompletionError:
        raise
    except (ValueError, AttributeError, UnicodeError) as exc:
        raise CompletionError("Antigravity returned incomplete or invalid output",
                              diagnostic_code=f"{_CODE}-OUTPUT") from exc
    return content.strip(), usage
