// Local transport of the existing model projection, after canonical validation.
import { createHash } from 'node:crypto';

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  }
  return value;
}

export function projectRecord(record, sourceLines) {
  const excerpt = record.source.rawExcerpt;
  const bounded = record.statement.kind !== 'module_fact' && typeof excerpt === 'string'
    && [...excerpt].length <= 2000;
  const actual = sourceLines?.slice(record.source.lines.start - 1, record.source.lines.end).join('\n');
  const local = bounded && excerpt === actual;
  return {
    schemaVersion: record.schemaVersion,
    id: record.id,
    statement: record.statement,
    epistemic: record.epistemic,
    metadata: Object.fromEntries(Object.entries(record.metadata ?? {}).filter(([key]) => key !== 'generation')),
    source: {
      ...Object.fromEntries(['path', 'lines', 'symbol', 'extractor'].map(key => [key, record.source[key] ?? null])),
      // Editing uses bounded canonical excerpts; preserve their exact bytes.
      rawExcerpt: bounded && !local ? excerpt : undefined,
      excerpt_sha256: local ? createHash('sha256').update(excerpt).digest('hex') : undefined,
    },
    // Bind omitted evidence too: conflicting canonical IDs must still fail closed.
    record_digest: 'sha256-' + createHash('sha256').update(JSON.stringify(canonical(record))).digest('base64'),
  };
}
