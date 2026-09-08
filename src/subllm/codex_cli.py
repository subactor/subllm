"""Fixed Codex exec transport. Authentication remains inside the local CLI.

No target checkout, arbitrary argv, shell command or provider credential is
accepted. A private empty directory is the working root; this is not a VM.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .errors import CompletionError

MAX_BYTES = 1_000_000


def invoke(
    model: str,
    messages: Sequence[Mapping[str, Any]],
    timeout_seconds: float,
    response_format: Mapping[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    from .client import _terminate_worker_process_group

    executable = shutil.which("codex")
    if executable is None:
        raise CompletionError("local Codex executable unavailable", diagnostic_code="SUBLLM-CODEX-UNAVAILABLE")
    prompt = json.dumps({"messages": list(messages)}, ensure_ascii=False).encode()
    if len(prompt) > MAX_BYTES:
        raise CompletionError("Codex prompt exceeds byte budget", diagnostic_code="SUBLLM-CODEX-BUDGET")
    with tempfile.TemporaryDirectory(prefix="subllm-codex-") as directory:
        root = Path(directory)
        output = root / "answer.txt"
        argv = [executable, "exec", "--ignore-user-config", "--ephemeral",
                "--skip-git-repo-check", "--sandbox", "read-only", "--color", "never",
                "--json", "--model", model, "--output-last-message", str(output),
                "-c", "features.shell_tool=false", "-c", "features.multi_agent=false"]
        if response_format is not None:
            if response_format.get("type") != "json_schema":
                raise CompletionError("Codex requires a json_schema response format")
            schema = response_format.get("json_schema", {}).get("schema")
            if not isinstance(schema, Mapping):
                raise CompletionError("Codex response schema must be an object")
            schema_path = root / "response.schema.json"
            schema_path.write_text(json.dumps(schema))
            argv += ["--output-schema", str(schema_path)]
        argv.append("-")
        # Do not copy API credentials into the child. Codex owns ChatGPT login
        # through its normal HOME/CODEX_HOME location; we never open auth files.
        environment = {k: v for k, v in os.environ.items()
                       if k in {"HOME", "CODEX_HOME", "PATH", "LANG", "LC_ALL", "TMPDIR",
                                "SYSTEMROOT", "WINDIR", "SSL_CERT_FILE", "SSL_CERT_DIR"}}
        events_path = root / "events.jsonl"
        with (root / "prompt.json").open("wb+") as stdin, events_path.open("wb") as stdout:
            stdin.write(prompt)
            stdin.seek(0)
            process = subprocess.Popen(argv, stdin=stdin, stdout=stdout, stderr=subprocess.DEVNULL,
                                       cwd=root, env=environment, start_new_session=True)
            deadline = time.monotonic() + timeout_seconds
            try:
                while process.poll() is None:
                    if time.monotonic() >= deadline:
                        raise CompletionError("Codex attempt timed out", diagnostic_code="SUBLLM-CODEX-TIMEOUT")
                    if events_path.stat().st_size > MAX_BYTES or (
                        output.exists() and output.stat().st_size > MAX_BYTES
                    ):
                        raise CompletionError("Codex output exceeds byte budget",
                                              diagnostic_code="SUBLLM-CODEX-BUDGET")
                    time.sleep(min(0.05, max(0, deadline - time.monotonic())))
            finally:
                # Reap descendants even if the CLI exited before its children.
                _terminate_worker_process_group(process)
        if process.returncode != 0:
            raise CompletionError("Codex failed; check local CLI login and model access",
                                  diagnostic_code="SUBLLM-CODEX-FAILED")
        if not output.is_file() or output.stat().st_size > MAX_BYTES or events_path.stat().st_size > MAX_BYTES:
            raise CompletionError("Codex output missing or oversized", diagnostic_code="SUBLLM-CODEX-OUTPUT")
        try:
            events = [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]
            if any(e.get("type") in {"turn.failed", "error"} for e in events):
                raise ValueError("failed event")
            completed = [e for e in events if e.get("type") == "turn.completed"]
            if len(completed) != 1:
                raise ValueError("missing completion")
            content = output.read_text().strip()
            if not content:
                raise ValueError("empty answer")
            raw_usage = completed[0].get("usage", {})
            if not isinstance(raw_usage, dict):
                raise ValueError("invalid usage")
            usage = {k: v for k, v in raw_usage.items()
                     if k in {"input_tokens", "output_tokens", "cached_input_tokens"}
                     and type(v) is int and v >= 0}
        except (ValueError, AttributeError, UnicodeError) as exc:
            raise CompletionError("Codex returned incomplete or invalid output",
                                  diagnostic_code="SUBLLM-CODEX-OUTPUT") from exc
        return content, usage
