"""Canonical record normalization for code2dsl output."""
from __future__ import annotations

from .code_context_primitives import digest
from .errors import CompletionError


def restore_excerpt(source: dict, lines: list[str]) -> None:
    """Reconstruct only an exact bounded canonical excerpt bound by the extractor."""
    if 'excerpt_sha256' not in source:
        return
    span = source['lines']
    excerpt = '\n'.join(lines[span['start'] - 1:span['end']])
    if len(excerpt) > 2000 or digest(excerpt.encode()) != source['excerpt_sha256']:
        raise CompletionError('code2dsl canonical excerpt digest mismatch')
    source['rawExcerpt'] = excerpt


def unique_records(records: list[dict]) -> list[dict]:
    """Canonical extractors may repeat the same fact; conflicting IDs remain invalid."""
    unique = {}
    for record in records:
        identity = record['id']
        if identity in unique and unique[identity] != record:
            raise CompletionError('code2dsl returned conflicting source identity')
        unique.setdefault(identity, record)
    return list(unique.values())
