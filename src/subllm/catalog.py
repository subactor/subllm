"""Versioned catalog data; adapters and execution authority remain in code.

Activation is process-local and explicit: SUBLLM_CATALOG_FILE plus the raw file
SUBLLM_CATALOG_SHA256 pin. Existing Python defaults and runtime TOML remain the
compatibility path for the migration release. A content pin is not approval.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import tomllib
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

from .errors import InvalidPolicyError
from .types import ApplicationSpec, ModelSpec, ProviderModelSpec, RouteCandidate, RoutePolicy

SCHEMA = "subllm.catalog/v1"
FILE_ENV = "SUBLLM_CATALOG_FILE"
PIN_ENV = "SUBLLM_CATALOG_SHA256"
MAX_BYTES = 1_048_576
IDENTIFIER = r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}"


def _fail(message):
    raise InvalidPolicyError("catalog: " + message)


def canonical(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        encoded.encode("utf-8")
        return encoded
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail("document is not bounded JSON data")


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def _object(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        _fail("invalid object fields")
    return value


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(IDENTIFIER, value):
        _fail("invalid identifier")
    return value


def _text(value, maximum, *, empty=False):
    if (not isinstance(value, str) or (not value and not empty) or len(value) > maximum
            or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        _fail("invalid text field")
    return value


def _integer(value):
    if type(value) is not int or not 0 <= value <= 10000:
        _fail("priority must be an integer from 0 to 10000")
    return value


def _boolean(value):
    if type(value) is not bool:
        _fail("expected boolean")
    return value


def _mapping(value, maximum):
    if not isinstance(value, dict) or not 1 <= len(value) <= maximum:
        _fail("invalid catalog collection")
    for key in value:
        _identifier(key)
    return value


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            _fail("duplicate field")
        value[key] = item
    return value


def read_document(path: Path, *, maximum=MAX_BYTES):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts or any(p.is_symlink() for p in (path, *path.parents)):
        _fail("file must be absolute and contain no symlink or parent escape")
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                _fail("file must be regular")
            raw = stream.read(maximum + 1)
        if len(raw) > maximum:
            _fail("file exceeds byte limit")
        text = raw.decode("utf-8")
        value = tomllib.loads(text) if path.suffix == ".toml" else json.loads(text, object_pairs_hook=_pairs)
    except (OSError, UnicodeError, ValueError, RecursionError):
        _fail("cannot read catalog data")
    return value, hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class CompiledCatalog:
    providers: Mapping
    models: Mapping
    applications: Mapping
    routes: Mapping
    provider_defaults: Mapping
    sha256: str
    canonical_json: str


def compile_catalog(document, *, adapters=None, legacy_models=None):
    """Validate shape and graph before constructing any runtime registration."""
    if adapters is None or legacy_models is None:
        from .policy import _BASE_MODELS, _BASE_PROVIDERS
        adapters, legacy_models = _BASE_PROVIDERS, _BASE_MODELS
    document = _object(document, {"schema", "version", "providers", "models", "applications", "routes"})
    if len(canonical(document).encode()) > MAX_BYTES:
        _fail("catalog exceeds byte limit")
    document = copy.deepcopy(document)
    if document["schema"] != SCHEMA or type(document["version"]) is not int or document["version"] != 1:
        _fail("unsupported version")
    provider_rows = _mapping(document["providers"], 32)
    if set(provider_rows) != set(adapters):
        _fail("provider adapters must match the code-owned registry")
    defaults = {}
    for name, row in provider_rows.items():
        row = _object(row, {"api_base", "api_key_env", "transport", "attribution_headers",
                            "enabled", "priority", "default_model"})
        fixed = asdict(adapters[name])
        if any(type(row[k]) is not type(fixed[k]) or row[k] != fixed[k]
               for k in ("api_base", "api_key_env", "transport", "attribution_headers")):
            _fail("adapter endpoint, credential and transport bindings cannot change")
        defaults[name] = MappingProxyType({"enabled": _boolean(row["enabled"]),
                                          "priority": _integer(row["priority"]),
                                          "default_model": _identifier(row["default_model"])})
    forbidden = {(p, wire.wire_model) for model in legacy_models.values() if model.forbidden
                 for p, wire in model.providers.items()}
    prefixes = {p: {v.litellm_model[:-len(v.wire_model)]
                    for m in legacy_models.values() for name, v in m.providers.items()
                    if name == p and v.litellm_model} for p in adapters}
    models = {}
    for name, row in _mapping(document["models"], 4096).items():
        row = _object(row, {"providers", "vision", "forbidden"})
        banned, vision = _boolean(row["forbidden"]), _boolean(row["vision"])
        if name in legacy_models and legacy_models[name].forbidden and not banned:
            _fail("a code-forbidden model cannot be enabled")
        variants = row["providers"]
        if (not isinstance(variants, dict) or len(variants) > len(adapters) or (not variants and not banned)
                or any(p not in adapters for p in variants)):
            _fail("invalid model provider variants")
        values = {}
        for provider, variant in variants.items():
            variant = _object(variant, {"litellm_model", "wire_model"})
            wire = _identifier(variant["wire_model"])
            litellm = variant["litellm_model"]
            if litellm:
                _identifier(litellm)
            elif litellm != "":
                _fail("invalid model alias")
            if (litellm and not any(litellm == prefix + wire for prefix in prefixes[provider])) or (
                    not litellm and prefixes[provider]):
                _fail("model alias must retain the code-owned adapter prefix and wire identity")
            if not banned and (provider, wire) in forbidden:
                _fail("alias cannot enable a forbidden wire model")
            if provider == "openrouter" and (name.startswith("gpt-5.6-sol")
                                             or wire.rsplit("/", 1)[-1].startswith("gpt-5.6-sol")):
                _fail("Cursor Sol is not an OpenRouter model")
            values[provider] = ProviderModelSpec(litellm, wire)
        models[name] = ModelSpec(name, MappingProxyType(values), banned, vision)
    for name, row in defaults.items():
        model = models.get(row["default_model"])
        if model is None or model.forbidden or name not in model.providers:
            _fail("default model must be permitted through its provider")
    priorities = [value["priority"] for value in defaults.values() if value["enabled"]]
    if len(priorities) != len(set(priorities)):
        _fail("enabled providers must have unique priorities")
    apps = {}
    for name, row in _mapping(document["applications"], 2048).items():
        row = _object(row, {"title", "url"})
        if not 6 <= len(name) <= 128:
            _fail("application ID must contain 6..128 characters")
        title, url = _text(row["title"], 100), _text(row["url"], 2048)
        try:
            parsed = urlsplit(url)
        except ValueError:
            _fail("invalid application URL")
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or any(c.isspace() for c in url)):
            _fail("application URL must be public HTTPS without credentials or query")
        apps[name] = ApplicationSpec(name, title, url)
    rows = document["routes"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        _fail("invalid routes collection")
    routes = {}
    for row in rows:
        row = _object(row, {"application", "function", "modality", "candidates"})
        app, function = _identifier(row["application"]), _identifier(row["function"])
        modality = row["modality"]
        if app not in apps or (app, function) in routes or modality not in ("text", "vision"):
            _fail("unknown/duplicate route or modality")
        raw = row["candidates"]
        if not isinstance(raw, list) or not 1 <= len(raw) <= 32:
            _fail("route must have 1..32 candidates")
        candidates, seen = [], set()
        for item in raw:
            required = {"provider", "priority_offset", "model_parameters"}
            if not isinstance(item, dict) or not required <= set(item) <= required | {"model"}:
                _fail("invalid candidate fields")
            provider, alias = item["provider"], item.get("model")
            if (not isinstance(provider, str) or provider not in adapters
                    or (alias is not None and not isinstance(alias, str))):
                _fail("unknown candidate provider or model")
            if alias is not None:
                _identifier(alias)
            else:
                item.pop("model", None)  # TOML omits null; both forms have one semantic identity.
            model = models.get(alias or defaults[provider]["default_model"])
            if model is None or model.forbidden or provider not in model.providers:
                _fail("candidate model is unavailable or forbidden")
            offset = _integer(item["priority_offset"])
            params = item["model_parameters"]
            if (not isinstance(params, dict) or set(params) - {"reasoning_effort", "verbosity"}
                    or any(v not in ("low", "medium", "high") for v in params.values())):
                _fail("model parameters exceed bounded overrides")
            identity = canonical(item)
            if identity in seen:
                _fail("duplicate candidate")
            seen.add(identity)
            if modality == "vision" and (not model.vision or adapters[provider].transport != "openai-compatible"):
                _fail("vision route requires a declared vision model and OpenAI-compatible transport")
            candidates.append(RouteCandidate(provider, alias, offset, model_parameters=MappingProxyType(dict(params))))
        priorities = [defaults[c.provider]["priority"] + c.priority_offset for c in candidates
                      if defaults[c.provider]["enabled"]]
        if not priorities or len(priorities) != len(set(priorities)):
            _fail("route needs enabled candidates with unique effective priorities")
        routes[(app, function)] = RoutePolicy(app, function, tuple(candidates), modality)
    encoded = canonical(document)
    if len(encoded.encode()) > MAX_BYTES:
        _fail("catalog exceeds byte limit")
    return CompiledCatalog(MappingProxyType(dict(adapters)), MappingProxyType(models), MappingProxyType(apps),
                           MappingProxyType(routes), MappingProxyType(defaults), digest(document), encoded)


def load_catalog(path, expected_sha256, *, adapters=None, legacy_models=None):
    if not isinstance(expected_sha256, str) or not re.fullmatch("[a-f0-9]{64}", expected_sha256):
        _fail("an explicit raw-file SHA256 pin is required")
    value, observed = read_document(Path(path))
    if observed != expected_sha256:
        _fail("file pin mismatch")
    return compile_catalog(value, adapters=adapters, legacy_models=legacy_models)


def export_catalog():
    """Export semantic defaults without resolving credentials or runtime overrides."""
    from . import policy
    from .policy_config import _DEFAULTS
    if policy.CATALOG_DOCUMENT is not None:
        return json.loads(policy.CATALOG_DOCUMENT)
    return {"schema": SCHEMA, "version": 1,
            "providers": {k: {**{f: v for f, v in asdict(p).items() if f != "id"}, **asdict(_DEFAULTS[k])}
                          for k, p in policy._BASE_PROVIDERS.items()},
            "models": {k: {"vision": m.vision, "forbidden": m.forbidden,
                            "providers": {p: asdict(v) for p, v in m.providers.items()}}
                       for k, m in policy._BASE_MODELS.items()},
            "applications": {k: {"title": a.title, "url": a.url} for k, a in policy.APPLICATIONS.items()},
            "routes": [{"application": r.application, "function": r.function, "modality": r.modality,
                        "candidates": [{"provider": c.provider, **({"model": c.model} if c.model is not None else {}),
                                        "priority_offset": c.priority_offset,
                                        "model_parameters": dict(c.model_parameters)}
                                       for c in r.candidates]} for r in policy.ROUTES.values()]}


@lru_cache(maxsize=1)
def catalog_digest():
    return digest(export_catalog())


def effective_digest(runtime, route):
    """Semantic evidence contains no credential values and grants no authority."""
    concrete = route.public_dict()
    concrete.pop("policy_sha256", None)
    return digest({"catalog": catalog_digest(),
                   "providers": {k: asdict(v) for k, v in runtime.providers.items()},
                   "applications": {k: asdict(v) for k, v in runtime.applications.items()},
                   "custom_providers": {k: asdict(v) for k, v in runtime.custom_providers.items()},
                   "execution": asdict(runtime.execution), "route": concrete})
