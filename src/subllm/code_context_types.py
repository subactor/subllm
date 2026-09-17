"""Source-bound code2dsl context model; original file bodies stay local."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .code_context_primitives import digest


@dataclass
class CodeContext:
    records: list[dict[str, Any]]
    sources: dict[str, bytes] = field(repr=False)
    runtime_receipt: dict[str, str]
    warnings: list[str] = field(default_factory=list)

    def projection(self, record: dict[str, Any]) -> dict[str, Any]:
        # No rawExcerpt, arbitrary extractor metadata or original file bodies.
        source = record['source']
        return {
            'schemaVersion': record['schemaVersion'], 'id': record['id'],
            'statement': record['statement'], 'epistemic': record['epistemic'],
            'metadata': {k: v for k, v in record.get('metadata', {}).items() if k != 'generation'},
            'source': {key: source.get(key) for key in ('path', 'lines', 'symbol', 'extractor')},
            'file_sha256': digest(self.sources[source['path']]),
        }
