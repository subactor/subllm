from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .client_routes import complete
from .client_types import CodeEditResponse
from .errors import CompletionError


def execute_code_edit(
    application: str,
    function: str,
    prompt: str,
    *,
    worktree: str | Path,
    provider: str | None = None,
    aider_bin: str = "aider",
    timeout_seconds: float = 2700.0,
    environ: Mapping[str, str] | None = None,
) -> CodeEditResponse:
    """Execute model-selected code2dsl edits through the canonical completion routes.

    ``aider_bin`` remains a validated compatibility input for deployed workers;
    no Aider process receives source files or executes in this implementation.
    """
    from .credential_env import merged_environment
    from .dsl_edit import execute_dsl_edit

    root = Path(worktree).resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise CompletionError("code edit worktree must be an existing Git worktree")
    if not prompt.strip() or len(prompt.encode("utf-8")) > 100_000:
        raise CompletionError("code edit task must contain 1 to 100000 UTF-8 bytes")
    if Path(aider_bin).name != "aider":
        raise CompletionError("code edit adapter requires an aider executable compatibility value")
    if (application, function) != ("onedev-agent", "code-edit"):
        raise CompletionError("code2dsl editing requires the registered onedev-agent/code-edit route")
    selected_provider, model, response = execute_dsl_edit(
        root, prompt, provider=provider, environ=merged_environment(environ=environ),
        timeout_seconds=timeout_seconds, complete=complete,
    )
    return CodeEditResponse(selected_provider, model, response)


def code_edit_main(argv: Sequence[str] | None = None) -> int:
    """Dedicated, closed CLI adapter for governed coding-agent execution."""
    parser = argparse.ArgumentParser(prog="subllm-code-edit")
    parser.add_argument("application")
    parser.add_argument("function")
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--prompt-file", type=Path, required=True)
    parser.add_argument("--provider")
    parser.add_argument("--aider-bin", default="aider")
    parser.add_argument("--timeout", type=float, default=2700.0)
    args = parser.parse_args(argv)
    try:
        prompt = args.prompt_file.read_text(encoding="utf-8")
        result = execute_code_edit(
            args.application,
            args.function,
            prompt,
            worktree=args.worktree,
            provider=args.provider,
            aider_bin=args.aider_bin,
            timeout_seconds=args.timeout,
        )
    except (OSError, UnicodeError, CompletionError) as exc:
        print(f"subllm-code-edit: {exc}")
        return 2
    print(json.dumps({
        "schema": "subllm.code-edit-result/v1",
        "status": "SUCCESS",
        "provider": result.provider,
        "model": result.model,
        "response": result.response,
    }, ensure_ascii=False, sort_keys=True))
    return 0
