"""Transport schema for proposals. Semantic validation remains deterministic code."""
from __future__ import annotations

from .catalog import IDENTIFIER, SCHEMA


def schema():
    text_id = {"type": "string", "pattern": "^" + IDENTIFIER + "$"}
    priority = {"type": "integer", "minimum": 0, "maximum": 10000}

    def obj(properties):
        return {"type": "object", "properties": properties, "required": list(properties),
                "additionalProperties": False}

    def collection(value, maximum, minimum=1):
        return {"type": "object", "propertyNames": text_id, "additionalProperties": value,
                "minProperties": minimum, "maxProperties": maximum}

    provider = obj({"api_base": {"type": "string"}, "api_key_env": {"type": "string"},
                    "transport": {"enum": ["openai-compatible", "cursor-sdk", "gemini-sdk", "anthropic",
                                            "codex-cli", "claude-cli", "agy-cli", "cursor-cli"]},
                    "attribution_headers": {"type": "boolean"}, "enabled": {"type": "boolean"},
                    "priority": priority, "default_model": text_id})
    parameters = {"type": "object", "properties": {
        key: {"enum": ["low", "medium", "high"]} for key in ("reasoning_effort", "verbosity")},
        "additionalProperties": False}
    candidate = obj({"provider": text_id, "model": {"anyOf": [text_id, {"type": "null"}]},
                     "priority_offset": priority, "model_parameters": parameters})
    candidate["required"].remove("model")
    variant = obj({"litellm_model": {"anyOf": [text_id, {"const": ""}]}, "wire_model": text_id})
    model = obj({"vision": {"type": "boolean"}, "forbidden": {"type": "boolean"},
                 "providers": collection(variant, 32, 0)})
    app = obj({"title": {"type": "string", "minLength": 1, "maxLength": 100},
               "url": {"type": "string", "minLength": 1, "maxLength": 2048}})
    route = obj({"application": text_id, "function": text_id, "modality": {"enum": ["text", "vision"]},
                 "candidates": {"type": "array", "minItems": 1, "maxItems": 32, "uniqueItems": True,
                                "items": candidate}})
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "urn:subllm:catalog:schema:v1", **obj({"schema": {"const": SCHEMA},
            "version": {"type": "integer", "const": 1}, "providers": collection(provider, 32),
            "models": collection(model, 4096), "applications": collection(app, 2048),
            "routes": {"type": "array", "minItems": 1, "maxItems": 4096, "items": route}})}
