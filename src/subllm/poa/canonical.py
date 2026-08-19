from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_SHA256 = re.compile(r"^[a-f0-9]{64}$")


def rfc8785(value: Any) -> str:
    """Canonicalize the accepted SubLLM document domain as RFC 8785 JSON."""
    return _encode(value)


def sha256_hex(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return hashlib.sha256(payload).hexdigest()


def digest_document(value: Any) -> str:
    return sha256_hex(rfc8785(value))


def require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(label)
    return value


def _encode(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        return "[" + ",".join(_encode(item) for item in value) + "]"
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical object keys must be strings")
        members = ",".join(f"{_encode(key)}:{_encode(value[key])}" for key in sorted(value))
        return "{" + members + "}"
    raise TypeError("value is outside the RFC8785 document domain")
