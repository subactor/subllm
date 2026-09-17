"""Canonical JSON encoding and SHA-256 digests for code2dsl evidence."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def encode(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
