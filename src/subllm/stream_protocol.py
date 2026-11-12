"""Bounded native SSE framing and provider event normalization.

Provider event IDs, when supplied, deduplicate identical retransmissions. Chat
completion IDs identify the whole request and are deliberately not event IDs.
Text/tool fragments are provisional; only the terminal provider turn supplies
final usage. Hidden thinking content is not projected as visible text.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping

from .gemini_api import usage_from_metadata
from .native_http import decode_response_json

MAX_LINE = 65_536
MAX_EVENT = 262_144
MAX_STREAM = 4_000_000
MAX_OUTPUT = 1_000_000


class StreamProtocolError(ValueError):
    pass


def sse_events(response):
    total = size = 0
    lines, event, identity = [], "", ""
    seen = {}
    first = True
    while True:
        line = response.readline(MAX_LINE + 1)
        total += len(line)
        if len(line) > MAX_LINE or total > MAX_STREAM:
            raise StreamProtocolError("stream bound exceeded")
        if not line:
            if lines:
                raise StreamProtocolError("truncated SSE frame")
            return
        text = line.decode("utf-8-sig" if first else "utf-8").rstrip("\r\n")
        first = False
        if not text:
            if lines:
                data = "\n".join(lines)
                digest = hashlib.sha256((event + "\n" + data).encode()).hexdigest()
                if identity and identity in seen:
                    if seen[identity] != digest:
                        raise StreamProtocolError("conflicting event ID")
                else:
                    if identity:
                        if len(seen) >= 8192:
                            raise StreamProtocolError("too many event IDs")
                        seen[identity] = digest
                    yield event, identity, data
            lines, event, identity, size = [], "", "", 0
            continue
        if text.startswith(":"):
            continue
        field, _, value = text.partition(":")
        value = value.removeprefix(" ")
        if field == "data":
            size += len(line)
            if size > MAX_EVENT:
                raise StreamProtocolError("event bound exceeded")
            lines.append(value)
        elif field == "event":
            if len(value) > 128:
                raise StreamProtocolError("invalid event type")
            event = value
        elif field == "id":
            if "\0" in value or len(value) > 512:
                raise StreamProtocolError("invalid event ID")
            identity = value


def _counts(value):
    if not isinstance(value, Mapping):
        raise StreamProtocolError("invalid usage")
    result = {}
    for name in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens", "total_tokens",
                 "cache_read_input_tokens", "cached_input_tokens"):
        if name in value:
            count = value[name]
            if type(count) is not int or count < 0:
                raise StreamProtocolError("invalid usage counter")
            result[name] = count
    details = value.get("prompt_tokens_details")
    cached = details.get("cached_tokens") if isinstance(details, Mapping) else None
    prompt = result.get("prompt_tokens")
    if type(cached) is int and type(prompt) is int and 0 <= cached <= prompt:
        result["cached_input_tokens"] = cached
    return result


class NativeStream:
    """Accumulate one provider turn; never executes a tool or resumes a prefix."""

    def __init__(self, transport, *, bounded=False):
        self.transport, self.bounded = transport, bounded
        self.content, self.usage, self.finish_reason = "", {}, ""
        self.done = self.tools = self.started = self.final_usage = False
        self.blocks = {}
        self.output_bytes = 0

    def _text(self, text):
        if not isinstance(text, str):
            raise StreamProtocolError("invalid text delta")
        self.output_bytes += len(text.encode())
        if self.output_bytes > MAX_OUTPUT:
            raise StreamProtocolError("output bound exceeded")
        self.content += text
        return "text_delta", text, ""

    def _tool(self, tool):
        data = json.dumps(tool, ensure_ascii=True, separators=(",", ":"))
        self.output_bytes += len(data)
        if self.output_bytes > MAX_OUTPUT:
            raise StreamProtocolError("tool output bound exceeded")
        self.tools = True
        return "tool_call_delta", "", data

    def feed(self, event, data):
        if self.done:
            raise StreamProtocolError("event after terminal")
        if data == "[DONE]":
            if self.transport != "openai-compatible" or not self.finish_reason:
                raise StreamProtocolError("premature terminal")
            self.done = True
            return []
        raw = decode_response_json(data.encode())
        if not isinstance(raw, dict) or "error" in raw or raw.get("type") == "error":
            raise StreamProtocolError("provider stream error")
        if self.transport == "openai-compatible":
            return self._openai(raw)
        if self.transport == "anthropic":
            return self._anthropic(event, raw)
        return self._gemini(raw)

    def _openai(self, raw):
        result = []
        choices = raw.get("choices")
        if not isinstance(choices, list) or len(choices) > 1:
            raise StreamProtocolError("invalid stream choices")
        if choices:
            choice = choices[0]
            if not isinstance(choice, dict) or choice.get("index", 0) != 0:
                raise StreamProtocolError("invalid choice index")
            delta = choice.get("delta", {})
            if not isinstance(delta, dict) or self.finish_reason:
                raise StreamProtocolError("delta after finish")
            if delta.get("content") is not None:
                result.append(self._text(delta["content"]))
            if delta.get("tool_calls"):
                result.append(self._tool(delta["tool_calls"]))
            if choice.get("finish_reason") is not None:
                if not isinstance(choice["finish_reason"], str) or not choice["finish_reason"]:
                    raise StreamProtocolError("invalid finish reason")
                self.finish_reason = choice["finish_reason"]
        if raw.get("usage") is not None:
            if choices or not self.finish_reason:
                raise StreamProtocolError("usage before finish")
            self.usage = _counts(raw["usage"])
            self.final_usage = True
            result.append(("usage", "", json.dumps(self.usage)))
        return result

    def _anthropic(self, event, raw):
        kind = raw.get("type")
        if event and event != kind:
            raise StreamProtocolError("event type mismatch")
        if kind == "ping":
            return []
        if kind == "message_start":
            if self.started:
                raise StreamProtocolError("duplicate message start")
            self.started = True
            self.usage = _counts(raw["message"].get("usage", {}))
            return []
        if not self.started:
            raise StreamProtocolError("event before message start")
        index = raw.get("index")
        if kind == "content_block_start":
            if type(index) is not int or index < 0 or index in self.blocks or len(self.blocks) >= 1024:
                raise StreamProtocolError("invalid block start")
            block = raw["content_block"]
            self.blocks[index] = block["type"]
            if block["type"] == "text" and block.get("text"):
                return [self._text(block["text"])]
            if block["type"] == "tool_use":
                return [self._tool({"index": index, "id": block.get("id"),
                                    "name": block.get("name"), "input": block.get("input", {})})]
        elif kind == "content_block_delta":
            if index not in self.blocks or self.blocks[index] is None:
                raise StreamProtocolError("delta outside block")
            delta = raw["delta"]
            if delta["type"] == "text_delta":
                if self.blocks[index] != "text":
                    raise StreamProtocolError("text in nontext block")
                return [self._text(delta["text"])]
            if delta["type"] == "input_json_delta":
                if self.blocks[index] != "tool_use" or not isinstance(delta["partial_json"], str):
                    raise StreamProtocolError("invalid tool delta")
                return [self._tool({"index": index, "partial_json": delta["partial_json"]})]
        elif kind == "content_block_stop":
            if index not in self.blocks or self.blocks[index] is None:
                raise StreamProtocolError("invalid block stop")
            self.blocks[index] = None
        elif kind == "message_delta":
            if any(value is not None for value in self.blocks.values()) or self.finish_reason:
                raise StreamProtocolError("message delta before block stop")
            self.finish_reason = raw["delta"].get("stop_reason") or ""
            self.usage.pop("output_tokens", None)
            self.usage.update(_counts(raw.get("usage", {})))
            self.final_usage = True
            return [("usage", "", json.dumps(self.usage))]
        elif kind == "message_stop":
            if not self.finish_reason:
                raise StreamProtocolError("premature message stop")
            self.done = True
        return []

    def _gemini(self, raw):
        result = []
        candidates = raw.get("candidates", [])
        if not isinstance(candidates, list) or len(candidates) > 1:
            raise StreamProtocolError("invalid Gemini candidates")
        if candidates:
            candidate = candidates[0]
            if candidate.get("index", 0) != 0 or self.finish_reason:
                raise StreamProtocolError("candidate after finish")
            for part in candidate.get("content", {}).get("parts", []):
                if part.get("thought"):
                    continue
                if "text" in part:
                    result.append(self._text(part["text"]))
                if "functionCall" in part:
                    result.append(self._tool(part["functionCall"]))
            if candidate.get("finishReason"):
                self.finish_reason = str(candidate["finishReason"]).lower()
        if "usageMetadata" in raw:
            self.usage = usage_from_metadata(raw["usageMetadata"], bounded=self.bounded, strict=self.bounded)
            self.final_usage = bool(self.finish_reason)
            result.append(("usage", "", json.dumps(self.usage)))
        return result

    def finish(self):
        if self.transport == "gemini-sdk" and self.finish_reason:
            self.done = True  # Gemini terminates by EOF after the final candidate.
        if not self.done or not self.finish_reason:
            raise StreamProtocolError("stream ended without terminal")
        usage = dict(self.usage)
        if not self.final_usage:
            # Anthropic message_start counts are provisional, never a free result.
            usage.pop("output_tokens", None)
            usage.pop("completion_tokens", None)
        return {"content": self.content, "usage": usage, "finish_reason": self.finish_reason, "tools": self.tools}
