"""Safe public projection for persisted naming advice provenance."""

from __future__ import annotations

import re

from app.models.ingest import IngestTaskAiResult

_VERSION = re.compile(r"^V[1-9]\d*(?:\.\d+)*$")
_LEVELS = {"L1", "L2", "L3", "L4", "L5"}
_CONFIDENCE = {"high", "medium", "low"}


def safe_naming_advice(ai: IngestTaskAiResult | None) -> dict[str, str]:
    """Return stable defaults for legacy rows; never infer provenance from old values."""
    version = (ai.suggested_version or "").upper() if ai else ""
    version_source = ai.version_source if ai else None
    version_confidence = ai.version_confidence if ai else None
    reliable_version = bool(
        _VERSION.fullmatch(version)
        and (
            (version_source == "source_filename" and version_confidence == "high")
            or (version_source == "ai_content" and version_confidence in {"high", "medium"})
        )
    )
    if not reliable_version:
        version = "V1"
        version_source = "default_needs_confirmation"
        version_confidence = "low"
        version_reason = "未能可靠判断版本，已使用规则默认值"
    else:
        version_reason = {
            "source_filename": "从源文件名识别到标准版本",
            "ai_content": "AI 根据正文与可用元数据建议版本",
        }[version_source]
    if version_confidence not in _CONFIDENCE:
        version_confidence = "low"

    level = ai.suggested_confidentiality_level if ai else None
    confidentiality_source = ai.confidentiality_source if ai else None
    confidentiality_confidence = ai.confidentiality_confidence if ai else None
    reliable_confidentiality = (
        level in _LEVELS
        and confidentiality_source == "ai_content"
        and confidentiality_confidence in {"high", "medium"}
    )
    if not reliable_confidentiality:
        level = "L2"
        confidentiality_source = "default_needs_confirmation"
        confidentiality_confidence = "low"
        confidentiality_reason = "AI 未能可靠判断内容密级，已使用规则默认值"
    else:
        # Only return a server-owned summary. Never project stored model prose.
        confidentiality_reason = f"AI 根据正文内容特征建议为 {level}"
    return {
        "suggested_version": version,
        "version_source": version_source,
        "version_confidence": version_confidence,
        "version_reason": version_reason[:300],
        "suggested_confidentiality_level": level,
        "confidentiality_source": confidentiality_source,
        "confidentiality_confidence": confidentiality_confidence,
        "confidentiality_reason": confidentiality_reason[:300],
    }
