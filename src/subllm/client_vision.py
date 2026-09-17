from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .errors import CompletionError

MAX_VISION_DATA_URL_CHARS = 4_000_000
_IMAGE_URL_PREFIXES = ("data:image/", "https://")


def _image_url(part: Mapping[str, Any]) -> str:
    payload = part.get("image_url")
    if isinstance(payload, str):
        return payload
    if isinstance(payload, Mapping):
        return str(payload.get("url") or "")
    return ""


def _iter_image_urls(messages: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    urls: list[str] = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for part in content:
            if not isinstance(part, Mapping) or part.get("type") != "image_url":
                continue
            urls.append(_image_url(part))
    return tuple(urls)


def _validate_vision_messages(messages: Sequence[Mapping[str, Any]], *, modality: str) -> None:
    urls = _iter_image_urls(messages)
    if urls and modality != "vision":
        raise CompletionError("image content requires a vision SubLLM route")
    if modality != "vision":
        return
    if not urls:
        raise CompletionError("vision route requires at least one image_url part")
    for url in urls:
        if not url.startswith(_IMAGE_URL_PREFIXES):
            raise CompletionError("vision image_url must be an https or data:image URL")
        if url.startswith("data:image/") and len(url) > MAX_VISION_DATA_URL_CHARS:
            raise CompletionError("vision data URL exceeds the size limit")


def _message_text(messages: Sequence[Mapping[str, Any]]) -> str:
    """Serialize messages for Cursor's text-only SDK request API."""
    rendered: list[str] = []
    for message in messages:
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
        rendered.append(f"<{role}>\n{content}\n</{role}>")
    return "\n\n".join(rendered)
