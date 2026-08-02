"""Deterministic projection from legacy naming suggestions to a safe subject."""

from __future__ import annotations

import re
from pathlib import PurePath

_LEADING_CLASSIFICATION = re.compile(r"^\s*(?:【[^】]*】|\[[^\]]*\])\s*")
_LEGACY_TAIL = re.compile(
    r"_(?:[^_]+_)?(?:19|20)\d{6}_V[1-9]\d*(?:\.[1-9]\d*)*_L[1-5]\s*$",
    re.IGNORECASE,
)
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_LEGACY_COMPONENT = re.compile(
    r"(?:^|_)(?:19|20)\d{6}(?:_|$)|(?:^|_)V\d+(?:\.\d+)*(?:_|$)|(?:^|_)L[1-5](?:_|$)",
    re.IGNORECASE,
)


def _safe_candidate(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().split())
    if not normalized or len(normalized) > 120 or _UNSAFE.search(normalized):
        return None
    if _LEADING_CLASSIFICATION.match(normalized) or _LEGACY_COMPONENT.search(normalized):
        return None
    return normalized


def _extract_legacy_subject(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.strip().split())
    if not normalized:
        return None
    has_classification = bool(_LEADING_CLASSIFICATION.match(normalized))
    without_classification = _LEADING_CLASSIFICATION.sub("", normalized, count=1)
    has_legacy_tail = bool(_LEGACY_TAIL.search(without_classification))

    # An underscore is valid subject text. Only interpret it as a legacy field
    # separator after a legacy wrapper or the complete date/version/level tail
    # has positively identified the old naming format.
    if not has_classification and not has_legacy_tail:
        return _safe_candidate(normalized)

    without_tail = _LEGACY_TAIL.sub("", without_classification)
    # A recognized tail consumes its optional object/client segment. A partial
    # wrapped legacy value has no reliable boundary, so conservatively retain
    # only its first segment and never carry a possible client into the topic.
    topic = (without_tail if has_legacy_tail else without_classification.split("_", 1)[0]).strip()
    return _safe_candidate(topic)


def suggested_subject(
    naming_fields: dict | None,
    suggested_title: str | None,
    source_file_name: str,
) -> str | None:
    """Return a safe subject without mutating the persisted legacy suggestion."""
    topic = _safe_candidate((naming_fields or {}).get("topic"))
    if topic:
        return topic
    extracted = _extract_legacy_subject(suggested_title)
    if extracted:
        return extracted
    stem = PurePath(source_file_name).stem
    return _extract_legacy_subject(stem) or _safe_candidate(stem)
