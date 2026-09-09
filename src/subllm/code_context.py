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


def _tracked_files(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "-z"], cwd=root,
            capture_output=True, check=True, timeout=10,
        )
        return [name for name in result.stdout.decode("utf-8").split("\0") if name]
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise CompletionError("code edit repository context inventory failed") from exc


def write_aider_context_ignore(
    root: Path, selected: list[str], destination: Path, *, original: Path | None = None,
) -> None:
    """Keep extra tracked-file mentions from replacing an un-applied response.

    Aider adds mentioned files before applying edits. Its follow-up can discard
    the original patch. Preserve the repository ignore rules, then hide tracked
    files outside the explicitly selected context from automatic discovery.
    This affects discovery only; the outer executor still validates write scope.
    """
    original = original or root / ".aiderignore"
    if not original.is_absolute():
        original = root / original
    try:
        if original.is_symlink() or (original.exists() and not original.is_file()):
            raise CompletionError("code edit original Aider ignore file is not a regular file")
        inherited = original.read_text("utf-8") if original.is_file() else ""
        excluded = sorted(set(_tracked_files(root)) - set(selected))
        patterns = []
        for name in excluded:
            if "\n" in name or "\r" in name:
                raise CompletionError("code edit context inventory contains an unsupported filename")
            # Anchor exact names; do not interpret repository filenames as globs.
            escaped = re.sub(r"([\\*?\[\] ])", r"\\\1", name)
            patterns.append("/" + escaped)
        destination.write_text(inherited + "\n" + "\n".join(patterns) + "\n", "utf-8")
    except (OSError, UnicodeError) as exc:
        raise CompletionError("code edit Aider ignore projection failed") from exc


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


_PATH_TOKEN = re.compile(
    r"(?<![\w/@:.-])[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*(?![\w])"
)


def _prompt_path_references(prompt: str) -> set[str]:
    """Extract path tokens without splitting Unicode words such as 'testów'."""
    stripped = re.sub(r"https?://\S+", "", prompt)
    return {
        value.rstrip(".")
        for value in _PATH_TOKEN.findall(stripped)
        if not value.startswith(".")
    }


def _select_referenced_files(
    root: Path, references: set[str], *, max_files: int, max_bytes: int,
) -> list[str]:
    tracked = _tracked_files(root)
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


def select_code_context(
    root: Path, prompt: str, *, max_files: int = 48, max_bytes: int = 262_144,
) -> list[str]:
    """Select tracked files below exact task paths, plus explicitly named new files.

    An over-budget context fails visibly rather than silently omitting source
    files. Bare directory words that explode a tree are dropped in favor of
    slash-containing paths before that failure. Never recurse through untracked
    directories or dependency caches.
    """
    references = _prompt_path_references(prompt)
    try:
        return _select_referenced_files(
            root, references, max_files=max_files, max_bytes=max_bytes,
        )
    except CompletionError as exc:
        if "budget" not in str(exc):
            raise
        explicit = {ref for ref in references if "/" in ref}
        if not explicit or explicit == references:
            raise
        return _select_referenced_files(
            root, explicit, max_files=max_files, max_bytes=max_bytes,
        )
