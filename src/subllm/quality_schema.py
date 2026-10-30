"""Optional local JSON Schema acceptance, independent of provider wire format.

Draft 2020-12 assertions are supported; format remains an annotation. Schemas
must be self-contained. No remote or filesystem resource can be retrieved.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from .errors import QUALITY_VALIDATOR_ERROR_CODE, CompletionError, InvalidResponseContractError
from .quality import ResponseValidator


def _invalid_schema() -> InvalidResponseContractError:
    return InvalidResponseContractError(
        "quality_schema must be a bounded self-contained JSON Schema 2020-12",
        diagnostic_code=QUALITY_VALIDATOR_ERROR_CODE,
    )


def _pairs(items):
    result = {}
    for name, value in items:
        if name in result:
            raise ValueError("duplicate JSON key")
        result[name] = value
    return result


def _nonfinite(_value):
    raise ValueError("nonfinite JSON")


def declared_schema_gate(
    response_format: Mapping[str, Any] | None,
    predicate: ResponseValidator | None,
) -> ResponseValidator | None:
    """Enforce an existing wire schema as well as any explicit local contract."""
    if response_format is None:
        return predicate
    if not isinstance(response_format, Mapping):
        raise InvalidResponseContractError(
            "response_format must be an object",
            diagnostic_code=QUALITY_VALIDATOR_ERROR_CODE,
        )
    if response_format.get("type") != "json_schema":
        return predicate
    descriptor = response_format.get("json_schema")
    if not isinstance(descriptor, Mapping) or descriptor.get("schema") is None:
        raise InvalidResponseContractError(
            "response_format.json_schema requires a raw schema",
            diagnostic_code=QUALITY_VALIDATOR_ERROR_CODE,
        )
    return schema_gate(descriptor["schema"], predicate)


def schema_gate(
    schema: Mapping[str, Any] | bool | None,
    predicate: ResponseValidator | None,
) -> ResponseValidator | None:
    """Freeze and check the caller's contract before any paid provider request."""
    if schema is None:
        return predicate
    try:
        from jsonschema import Draft202012Validator
        from referencing import Registry, Resource
        from referencing.exceptions import NoSuchResource
        from referencing.jsonschema import DRAFT202012
    except ImportError:
        raise CompletionError(
            "response schema validator is unavailable", diagnostic_code=QUALITY_VALIDATOR_ERROR_CODE,
        ) from None
    try:
        if not isinstance(schema, (Mapping, bool)):
            raise _invalid_schema()
        # Bound traversal before serialization/metaschema recursion. This also
        # refuses cycles and non-string object keys rather than coercing them.
        pending, count = [(schema, 0)], 0
        while pending:
            node, depth = pending.pop()
            count += 1
            if count > 4096 or depth > 32:
                raise _invalid_schema()
            if isinstance(node, Mapping):
                if any(not isinstance(key, str) for key in node):
                    raise _invalid_schema()
                pending.extend((value, depth + 1) for value in node.values())
            elif isinstance(node, list):
                pending.extend((value, depth + 1) for value in node)
        encoded = json.dumps(schema, allow_nan=False)
        if len(encoded.encode("utf-8")) > 65_536:
            raise _invalid_schema()
        frozen = json.loads(encoded)
        Draft202012Validator.check_schema(frozen)

        def deny_retrieval(uri):
            raise NoSuchResource(ref=uri)

        resource = Resource.from_contents(frozen, default_specification=DRAFT202012)
        registry = Registry(retrieve=deny_retrieval).with_resource("", resource).crawl()
        resources = [(resource, registry.resolver().in_subresource(resource))]
        while resources:
            item, resolver = resources.pop()
            if isinstance(item.contents, dict):
                declared = item.contents.get("$schema", Draft202012Validator.META_SCHEMA["$id"])
                if declared.rstrip("#") != Draft202012Validator.META_SCHEMA["$id"]:
                    raise _invalid_schema()
                for name in ("$ref", "$dynamicRef"):
                    if name in item.contents:
                        ref = item.contents[name]
                        if not isinstance(ref, str) or not ref.startswith("#"):
                            raise _invalid_schema()
                        resolver.lookup(ref)
            resources.extend((child, resolver.in_subresource(child)) for child in item.subresources())
        validator = Draft202012Validator(frozen, registry=registry)
    except Exception:
        # Configuration, missing dependency and reference failures are caller
        # errors. Never turn them into another charged model attempt or echo
        # schema contents, reference URIs or third-party exception messages.
        raise _invalid_schema() from None

    def accepts(response):
        try:
            value = json.loads(response.content, object_pairs_hook=_pairs, parse_constant=_nonfinite)
        except (ValueError, RecursionError):
            return False
        if not validator.is_valid(value):
            return False
        return True if predicate is None else predicate(response)

    return accepts
