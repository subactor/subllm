"""Bounded file context for the noninteractive editing adapter.

Only task-referenced repository paths select content. This selection does not
grant write or shell authority.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path, PurePosixPath

from .errors import CompletionError

_TEXT_SUFFIXES = frozenset({
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".rs", ".go",
    ".java", ".c", ".h", ".cpp", ".hpp", ".cs", ".rb", ".php", ".sh",
    ".md", ".json", ".toml", ".yaml", ".yml", ".html", ".css", ".sql",
})
_EXCLUDED_NAMES = frozenset({"credentials.json", "credentials.yaml", "secrets.json", "secrets.yaml"})
_EXCLUDED_PARTS = frozenset({"node_modules", "vendor", "__pycache__"})


def _safe_file(root: Path, name: str) -> Path | None:
    path = PurePosixPath(name)
    if path.is_absolute() or any(
        part.startswith(".") or part in _EXCLUDED_PARTS for part in path.parts
    ):
        return None
    if path.suffix not in _TEXT_SUFFIXES or path.name.lower() in _EXCLUDED_NAMES:
        return None
    file = root / name
    # Do not follow even an in-repository link: the reviewed path must name the bytes.
    if any(parent.is_symlink() for parent in [file, *file.parents] if parent != root):
        return None
    return file if file.is_file() else None


def select_code_context(
    root: Path, prompt: str, *, max_files: int = 48, max_bytes: int = 262_144,
) -> list[str]:
    """Select tracked files below exact task paths, plus explicitly named new files.

    An over-budget context fails visibly rather than silently omitting source
    files. Never recurse through untracked directories or dependency caches.
    """
    references = {
        value.rstrip(".") for value in re.findall(
            r"(?<![\w/@:.-])[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*",
            re.sub(r"https?://\S+", "", prompt),
        ) if not value.startswith(".")
    }
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "-z"], cwd=root,
            capture_output=True, check=True, timeout=10,
        )
        tracked = result.stdout.decode("utf-8").split("\0")
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise CompletionError("code edit repository context inventory failed") from exc
    candidates = set(references)
    for name in tracked:
        path = PurePosixPath(name)
        if any(ref in references for ref in [name, *(str(p) for p in path.parents if str(p) != ".")]):
            candidates.add(name)
    selected: list[str] = []
    total = 0
    for name in sorted(candidates):
        file = _safe_file(root, name)
        if file is None:
            continue
        size = file.stat().st_size
        if len(selected) >= max_files or total + size > max_bytes:
            raise CompletionError("code edit context exceeds its file or byte budget")
        try:
            content = file.read_bytes()
            content.decode("utf-8")
        except (OSError, UnicodeError):
            continue
        if b"\0" in content:
            continue
        selected.append(name)
        total += len(content)
    return selected
