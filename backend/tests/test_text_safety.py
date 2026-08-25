from __future__ import annotations

import math

from app.core.text_safety import sanitize_json, sanitize_text


def test_text_safety_removes_postgres_controls_and_preserves_normal_unicode():
    result = sanitize_text("中文\x00 English\r\n第二行\t保留\x01\x7f\ud800🙂", max_chars=10_000)
    assert result.value == "中文 English\n第二行\t保留🙂"
    assert result.stats.removed_characters == 4
    assert result.stats.truncated is False


def test_text_safety_decodes_invalid_utf8_and_tracks_replacement():
    result = sanitize_text(b"valid\xfftext", max_chars=100)
    assert result.value == "valid\ufffdtext"
    assert result.stats.replaced_characters == 1


def test_json_safety_removes_non_json_values_and_sanitizes_nested_text():
    result = sanitize_json({"summary": "ok\x00", "values": [math.nan, math.inf, b"binary", "中文"]})
    assert result.value == {"summary": "ok", "values": [None, None, None, "中文"]}
    assert result.stats.removed_characters == 1
    assert result.stats.invalid_json_values == 3
