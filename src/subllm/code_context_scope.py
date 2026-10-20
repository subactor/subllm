"""Host-supplied context narrowing; admission and writer fencing remain with the host.

The v1 object binds canonical worktree, HEAD, native ticket and raw intent SHA256.
write_paths are exact intended files (including absent creates); read_paths are
explicit existing dependencies/tests. Neither list is inferred from prompt text.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .code_context_primitives import encode
from .code_context_safety import safe_path
from .errors import CompletionError


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate scope field')
        result[key] = value
    return result


def _read_document(path: Path, maximum: int) -> bytes:
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise CompletionError('code edit context document contains a symlink')
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        with os.fdopen(descriptor, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise CompletionError('code edit context document must be regular')
            data = stream.read(maximum + 1)
    except OSError as exc:
        raise CompletionError('code edit context document is unavailable') from exc
    if len(data) > maximum:
        raise CompletionError('code edit context document exceeds budget')
    return data


def load_scope(path: Path, sha256: str | None) -> dict:
    """Read only a bounded regular manifest matching the caller's expected digest."""
    if not isinstance(sha256, str) or not re.fullmatch('[a-f0-9]{64}', sha256):
        raise CompletionError('code edit context scope file or digest is invalid')
    data = _read_document(path, 65_536)
    if hashlib.sha256(data).hexdigest() != sha256:
        raise CompletionError('code edit context scope digest mismatch')
    try:
        result = json.loads(data, object_pairs_hook=_object)
    except (ValueError, UnicodeError) as exc:
        raise CompletionError('code edit context scope is invalid JSON') from exc
    return result


@dataclass(frozen=True)
class CodeEditScope:
    root: Path
    head: str
    ticket: str
    intent_sha256: str
    write_paths: tuple[str, ...]
    read_paths: tuple[str, ...]
    sha256: str

    def verify(self) -> None:
        """Observe current bindings, without minting a lease or approving an intent."""
        observed = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.root,
                                  capture_output=True, text=True, timeout=10, check=True)
        intent_path = self.root / 'project' / self.ticket / 'intent.json'
        if observed.stdout.strip() != self.head:
            raise CompletionError('code edit context scope binding is stale or unsafe')
        data = _read_document(intent_path, 262_144)
        if hashlib.sha256(data).hexdigest() != self.intent_sha256:
            raise CompletionError('code edit context intent binding is stale')
        intent = json.loads(data, object_pairs_hook=_object)
        allowed = intent.get('allowedPaths') if isinstance(intent, dict) else None
        if (not isinstance(intent, dict) or intent.get('ticket') != self.ticket or not isinstance(allowed, list)
                or not all(isinstance(p, str) and p for p in allowed)
                or any(not any(fnmatch.fnmatchcase(name, p) for p in allowed) for name in self.write_paths)):
            raise CompletionError('code edit context write paths exceed the bound intent')
        for name in (*self.write_paths, *self.read_paths):
            safe_path(self.root, name)

    def source_names(self, names: list[str]) -> list[str]:
        """Keep Git visibility and existing extractor ignore rules in force."""
        visible = set(names)
        for name in (*self.write_paths, *self.read_paths):
            file = safe_path(self.root, name)
            if name in self.read_paths and not file.is_file():
                raise CompletionError('code edit read context must exist')
            if file.exists() and (not file.is_file() or name not in visible):
                raise CompletionError('code edit context file is ignored or not regular')
        return sorted(visible.intersection((*self.write_paths, *self.read_paths)))

    def check_plan(self, selected: list[dict], answer: dict) -> None:
        self.verify()
        records = {r['id']: r for r in selected}
        for operation in ('edits', 'patches', 'json_updates', 'creates'):
            items = answer.get(operation, [])
            if not isinstance(items, list):
                raise CompletionError('code edit scoped operations must be arrays')
            for item in items:
                if not isinstance(item, dict):
                    raise CompletionError('code edit scoped operation is invalid')
                record = records.get(item.get('id')) if isinstance(item.get('id'), str) else None
                name = item.get('path') if operation == 'creates' else (
                    record['source']['path'] if record else None)
                if name not in self.write_paths:
                    raise CompletionError('code edit operation exceeds the supplied write scope')


def parse_scope(root: Path, value: dict | None) -> CodeEditScope | None:
    if value is None:
        return None
    root = root.resolve()
    rules = {'schema': lambda v: v == 'subllm.code-edit-scope/v1',
             'worktree': lambda v: v == str(root),
             'ticket': lambda v: _matches('ticket-[0-9]{3,}', v),
             'head_sha': lambda v: _matches('[a-f0-9]{40}', v),
             'intent_sha256': lambda v: _matches('[a-f0-9]{64}', v)}
    if (not isinstance(value, dict) or set(value) != {*rules, 'write_paths', 'read_paths'}
            or not all(validate(value[key]) for key, validate in rules.items())):
        raise CompletionError('code edit context scope identity is invalid')
    for field, minimum, maximum in (('write_paths', 1, 64), ('read_paths', 0, 256)):
        paths = value[field]
        if (not isinstance(paths, list) or not minimum <= len(paths) <= maximum
                or not all(isinstance(p, str) for p in paths) or len(set(paths)) != len(paths)):
            raise CompletionError('code edit context scope paths are invalid')
        for name in paths:
            safe_path(root, name)
    scope = CodeEditScope(root, value['head_sha'], value['ticket'], value['intent_sha256'],
                          tuple(value['write_paths']), tuple(value['read_paths']),
                          hashlib.sha256(encode(value).encode()).hexdigest())
    try:
        scope.verify()
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
        raise CompletionError('code edit context scope observation failed') from exc
    return scope


def _matches(pattern: str, value) -> bool:
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None
