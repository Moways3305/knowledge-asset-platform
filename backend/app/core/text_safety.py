"""Canonical PostgreSQL-safe text and JSON normalization for ingest boundaries."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

EXTRACTED_TEXT_MAX_CHARS = 200_000
CANONICAL_MARKDOWN_MAX_CHARS = 240_000
MODEL_RESPONSE_MAX_CHARS = 100_000
SUMMARY_MAX_CHARS = 2_000
ONE_LINER_MAX_CHARS = 200
TITLE_MAX_CHARS = 500
TAG_MAX_CHARS = 100
KEY_POINT_MAX_CHARS = 500
JSON_MAX_DEPTH = 12
JSON_MAX_ITEMS = 10_000


@dataclass(frozen=True, slots=True)
class SafetyStats:
    removed_characters: int = 0
    replaced_characters: int = 0
    invalid_json_values: int = 0
    truncated: bool = False

    def merge(self, other: SafetyStats) -> SafetyStats:
        return SafetyStats(
            removed_characters=self.removed_characters + other.removed_characters,
            replaced_characters=self.replaced_characters + other.replaced_characters,
            invalid_json_values=self.invalid_json_values + other.invalid_json_values,
            truncated=self.truncated or other.truncated,
        )

    def as_dict(self) -> dict[str, int | bool]:
        return {
            "removed_characters": self.removed_characters,
            "replaced_characters": self.replaced_characters,
            "invalid_json_values": self.invalid_json_values,
            "truncated": self.truncated,
        }


@dataclass(frozen=True, slots=True)
class SafeText:
    value: str
    stats: SafetyStats


@dataclass(frozen=True, slots=True)
class SafeJSON:
    value: Any
    stats: SafetyStats


def sanitize_text(value: str | bytes | None, *, max_chars: int) -> SafeText:
    if value is None:
        return SafeText("", SafetyStats())
    replaced = 0
    if isinstance(value, bytes):
        decoded = value.decode("utf-8", errors="replace")
        replaced = decoded.count("\ufffd")
        text = decoded
    else:
        text = str(value)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    output: list[str] = []
    removed = 0
    for character in text:
        codepoint = ord(character)
        if (
            codepoint == 0
            or 1 <= codepoint <= 8
            or codepoint in {11, 12}
            or 14 <= codepoint <= 31
            or codepoint == 127
            or 0xD800 <= codepoint <= 0xDFFF
        ):
            removed += 1
            continue
        output.append(character)
    normalized = "".join(output)
    truncated = len(normalized) > max_chars
    if truncated:
        normalized = normalized[:max_chars]
    return SafeText(
        normalized,
        SafetyStats(
            removed_characters=removed,
            replaced_characters=replaced,
            truncated=truncated,
        ),
    )


def sanitize_json(value: Any, *, string_max_chars: int = MODEL_RESPONSE_MAX_CHARS) -> SafeJSON:
    item_count = 0

    def visit(current: Any, depth: int) -> tuple[Any, SafetyStats]:
        nonlocal item_count
        item_count += 1
        if item_count > JSON_MAX_ITEMS or depth > JSON_MAX_DEPTH:
            return None, SafetyStats(invalid_json_values=1, truncated=True)
        if current is None or isinstance(current, (bool, int)):
            return current, SafetyStats()
        if isinstance(current, float):
            return (
                (current, SafetyStats())
                if math.isfinite(current)
                else (None, SafetyStats(invalid_json_values=1))
            )
        if isinstance(current, str):
            safe = sanitize_text(current, max_chars=string_max_chars)
            return safe.value, safe.stats
        if isinstance(current, (bytes, bytearray, memoryview)):
            return None, SafetyStats(invalid_json_values=1)
        if isinstance(current, (list, tuple)):
            result_list: list[Any] = []
            stats = SafetyStats()
            for item in current:
                safe_item, item_stats = visit(item, depth + 1)
                result_list.append(safe_item)
                stats = stats.merge(item_stats)
            return result_list, stats
        if isinstance(current, dict):
            result_dict: dict[str, Any] = {}
            stats = SafetyStats()
            for key, item in current.items():
                safe_key = sanitize_text(str(key), max_chars=500)
                safe_item, item_stats = visit(item, depth + 1)
                result_dict[safe_key.value] = safe_item
                stats = stats.merge(safe_key.stats).merge(item_stats)
            return result_dict, stats
        return None, SafetyStats(invalid_json_values=1)

    safe_value, stats = visit(value, 0)
    return SafeJSON(safe_value, stats)
