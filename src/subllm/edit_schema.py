"""Schema and record enrichment for subllm edit contract."""

from __future__ import annotations

import json

from .code_context import CodeContext, encode

SCHEMA = "subllm.edit-plan/v2"
MAX_CHANGE_BYTES = 262_144


def response_format(function: str, records: list[dict]) -> dict:
    """Make the wire response contract explicit, not merely a prose suggestion."""

    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}

    def array(items):
        return {"type": "array", "items": items}

    string = {"type": "string"}
    identity = {"type": "string", "enum": [r["id"] for r in records]} if records else string
    if function == "code-context":
        schema = obj({"ids": array(identity)})
    else:
        bound = {"id": identity, "file_sha256": string}
        schema = obj(
            {
                "schema": {"type": "string", "enum": [SCHEMA]},
                "summary": string,
                "edits": array(obj({**bound, "replacement": string})),
                "patches": array(obj({**bound, "before": string, "after": string})),
                "creates": array(obj({"path": string, "content": string})),
                "json_updates": array(obj({**bound, "pointer": array(string), "value": {}})),
            }
        )
    return {
        "type": "json_schema",
        "json_schema": {"name": function.replace("-", "_"), "strict": True, "schema": schema},
    }


def enrich_records(context: CodeContext, records: list[dict]) -> list[dict]:
    """Expose only canonical excerpts and bounded configuration value evidence."""
    originals = {r["id"]: r for r in context.records}
    result = []
    for record in records:
        original = originals[record["id"]]
        source = original["source"]
        excerpt = source.get("rawExcerpt")
        span = source["lines"]
        actual = "\n".join(context.sources[source["path"]].decode().splitlines()[span["start"] - 1 : span["end"]])
        patchable = (
            isinstance(excerpt, str)
            and bool(excerpt.strip())
            and len(excerpt) <= 2000
            and bool(actual)
            and original["statement"]["kind"] not in {"module_fact", "configuration_file_fact"}
        )
        extra = {"patchable": patchable, "patch_excerpt": excerpt if patchable else None}
        if (
            source["path"].endswith(".json")
            and original["statement"]["kind"] == "configuration_declaration"
            and original.get("metadata", {}).get("format") == "json"
        ):
            value = json.loads(context.sources[source["path"]])
            key = source.get("symbol")
            if isinstance(value, dict) and key in value:
                field = value[key]
                extra["json_field"] = {
                    "key": key,
                    "value": field if len(encode(field).encode()) <= 2000 else None,
                    "value_omitted": len(encode(field).encode()) > 2000,
                }
        if (source['path'].endswith('.json')
                and original['statement']['kind'] == 'configuration_file_fact'
                and original.get('metadata', {}).get('format') == 'json'
                and isinstance(json.loads(context.sources[source['path']]), dict)):
            extra['json_additions'] = True
        result.append({**record, **extra})
    return result
