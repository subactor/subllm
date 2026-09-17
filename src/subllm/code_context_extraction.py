"""Run the pinned public code2dsl API and read its bounded extraction output."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import tempfile
import zlib
from collections.abc import Mapping
from pathlib import Path

from .code_context_limits import MAX_DSL_BYTES, MAX_EXPANDED_DSL_BYTES, MAX_FILE_BYTES, MAX_SOURCE_BYTES
from .code_context_primitives import digest, encode
from .code_context_records import restore_excerpt, unique_records
from .code_context_safety import safe_path
from .code_context_types import CodeContext
from .errors import CompletionError


def runtime_digest(runtime: Path) -> str:
    """Pin executable JS, Python helpers and the TypeScript parser dependency."""
    value = hashlib.sha256()
    for directory in ('dist/src', 'python', 'node_modules/typescript'):
        base = runtime / directory
        if not base.is_dir() or base.is_symlink():
            raise CompletionError('code2dsl runtime build is incomplete')
        for file in sorted(base.rglob('*')):
            if file.is_symlink():
                raise CompletionError('code2dsl runtime build contains a symlink')
            if file.is_file() and file.suffix in {'.js', '.json', '.py'}:
                value.update(file.relative_to(runtime).as_posix().encode() + b'\0')
                value.update(bytes.fromhex(digest(file.read_bytes())))
    value.update((runtime / 'package.json').read_bytes())
    return value.hexdigest()


def read_extraction(output: Path) -> dict:
    """Bound the local transport and its expanded evidence projection."""
    if output.stat().st_size > MAX_DSL_BYTES:
        raise CompletionError('code2dsl output exceeds extraction budget')
    try:
        with gzip.open(output, 'rb') as stream:
            payload = stream.read(MAX_EXPANDED_DSL_BYTES + 1)
    except (OSError, EOFError, zlib.error) as exc:
        raise CompletionError('code2dsl compressed extraction is invalid') from exc
    if len(payload) > MAX_EXPANDED_DSL_BYTES:
        raise CompletionError('code2dsl expanded output exceeds extraction budget')
    return json.loads(payload)


def extract_context(root: Path, environ: Mapping[str, str]) -> CodeContext:
    try:
        return _extract_context(root, environ)
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as exc:
        raise CompletionError('code2dsl extraction or runtime observation failed') from exc


def _extract_context(root: Path, environ: Mapping[str, str]) -> CodeContext:
    """Run the pinned public code2dsl API against an isolated nonignored source snapshot."""
    location = environ.get('SUBLLM_CODE2DSL_RUNTIME', '')
    revision = environ.get('SUBLLM_CODE2DSL_SHA', '')
    build = environ.get('SUBLLM_CODE2DSL_BUILD_SHA256', '')
    if not location or len(revision) != 40 or len(build) != 64:
        raise CompletionError('code2dsl requires runtime, source SHA and independent build SHA256 pins')
    runtime = Path(location)
    if not runtime.is_absolute() or any(p.is_symlink() for p in [runtime, *runtime.parents]):
        raise CompletionError('code2dsl runtime must be an absolute non-symlink path')
    observed = subprocess.run(['git', '-C', str(runtime), 'rev-parse', 'HEAD'],
                              capture_output=True, check=True, timeout=10).stdout.decode().strip()
    if observed != revision or runtime_digest(runtime) != build:
        raise CompletionError('code2dsl runtime pin mismatch')
    names = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=root,
                           capture_output=True, check=True, timeout=10).stdout.decode().split('\0')
    sources: dict[str, bytes] = {}
    total = 0
    for name in sorted(set(names) - {''}):
        try:
            file = safe_path(root, name)
        except CompletionError:
            continue
        if not file.is_file():
            continue
        if file.stat().st_size > MAX_FILE_BYTES:
            raise CompletionError('code2dsl source file exceeds extraction budget')
        data = file.read_bytes()
        try:
            data.decode('utf-8')
        except UnicodeError:
            continue
        if b'\0' in data:
            continue
        total += len(data)
        if total > MAX_SOURCE_BYTES or len(sources) >= 20_000:
            raise CompletionError('code2dsl source snapshot exceeds extraction budget')
        sources[name] = data
    with tempfile.TemporaryDirectory(prefix='subllm-code2dsl-') as temporary:
        snapshot = Path(temporary) / 'source'
        snapshot.mkdir()
        for name in ('.gitignore', '.dockerignore', '.intentignore'):
            original = root / name
            if original.is_symlink():
                raise CompletionError('code2dsl ignore policy contains a symlink')
            if original.is_file():
                (snapshot / name).write_bytes(original.read_bytes())
        original = Path(environ.get('AIDER_AIDERIGNORE') or '.aiderignore')
        if not original.is_absolute():
            original = root / original
        if any(p.is_symlink() for p in [original, *original.parents]):
            raise CompletionError('code2dsl editor ignore policy contains a symlink')
        if original.exists():
            if not original.is_file():
                raise CompletionError('code2dsl editor ignore policy is not a regular file')
            with (snapshot / '.intentignore').open('ab') as handle:
                handle.write(b'\n' + original.read_bytes() + b'\n')
        for name, data in sources.items():
            file = snapshot / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(data)
        child_env = {k: v for k, v in os.environ.items() if k in {'PATH', 'SYSTEMROOT', 'LANG'}}
        output = Path(temporary) / 'records.json.gz'
        configuration_paths = Path(temporary) / 'configuration-paths.json'
        configuration_paths.write_text(encode([name for name in sources
                                               if Path(name).suffix in {'.json', '.toml', '.yaml', '.yml'}]))
        completed = subprocess.run(
            ['node', str(Path(__file__).with_name('code2dsl_bridge.mjs')), str(runtime), str(snapshot),
             str(output), str(configuration_paths)],
            cwd=temporary, env=child_env, capture_output=True, timeout=180, check=False,
        )
        if completed.returncode or not output.is_file():
            raise CompletionError('code2dsl extraction failed; no source-text fallback')
        envelope = read_extraction(output)
    records = unique_records(envelope['records'])
    source_lines: dict[str, list[str]] = {}
    for record in records:
        source = record['source']
        if record['schemaVersion'] != 't2c.intent/v1' or source['path'] not in sources:
            raise CompletionError('code2dsl returned invalid source identity')
        if source['path'] not in source_lines:
            source_lines[source['path']] = sources[source['path']].decode().split('\n')
        file_lines = source_lines[source['path']]
        lines = source['lines']
        if (not isinstance(lines, dict) or type(lines.get('start')) is not int
                or type(lines.get('end')) is not int
                or not 1 <= lines['start'] <= lines['end'] <= len(file_lines)):
            raise CompletionError('code2dsl returned invalid source range')
        restore_excerpt(source, file_lines)
    return CodeContext(records, sources, {'source_sha': revision, 'build_sha256': build}, envelope['warnings'])
