"""Path boundary validation for code2dsl source snapshots."""
from __future__ import annotations

from pathlib import Path, PurePosixPath

from .errors import CompletionError

_SUFFIXES = frozenset({'.py', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.md', '.json', '.toml', '.yaml', '.yml'})
_EXCLUDED = frozenset({'node_modules', 'vendor', '__pycache__'})


def safe_path(root: Path, name: str) -> Path:
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or path.as_posix() != name or '\\' in name
            or any(ord(c) < 32 for c in name)
            or any(p.startswith('.') or p in _EXCLUDED for p in path.parts)
            or path.suffix not in _SUFFIXES):
        raise CompletionError('code2dsl path is outside the source boundary')
    file = root / name
    if any(p.is_symlink() for p in [file, *file.parents]):
        raise CompletionError('code2dsl path contains a symlink')
    return file
