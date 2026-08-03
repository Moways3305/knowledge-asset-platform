"""Safe public projection for persisted naming advice provenance."""

from __future__ import annotations

import re
from typing import Literal, TypeAlias, TypedDict, cast

from app.models.ingest import IngestTaskAiResult
from app.schemas.enums import ConfidentialityLevel

_VERSION = re.compile(r"^V[1-9]\d*(?:\.\d+)*$")
_LEVELS = {"L1", "L2", "L3", "L4", "L5"}

VersionSource: TypeAlias = Literal["source_filename", "ai_content", "default_needs_confirmation"]
Confidence: TypeAlias = Literal["high", "medium", "low"]
ConfidentialitySource: TypeAlias = Literal["ai_content", "default_needs_confirmation"]


class NamingAdvice(TypedDict):
    """Typed public fields shared by naming and ingest response DTOs."""

    suggested_version: str
    version_source: VersionSource
    version_confidence: Confidence
    version_reason: str
    suggested_confidentiality_level: ConfidentialityLevel
    confidentiality_source: ConfidentialitySource
    confidentiality_confidence: Confidence
    confidentiality_reason: str


def safe_naming_advice(ai: IngestTaskAiResult | None) -> NamingAdvice:
    """Return stable defaults for legacy rows; never infer provenance from old values."""
    version = (ai.suggested_version or "").upper() if ai else ""
    version_source = ai.version_source if ai else None
    version_confidence = ai.version_confidence if ai else None
    if (
        _VERSION.fullmatch(version)
        and version_source == "source_filename"
        and version_confidence == "high"
    ):
        safe_version_source: VersionSource = "source_filename"
        safe_version_confidence: Confidence = "high"
        version_reason = "从源文件名识别到标准版本"
    elif (
        _VERSION.fullmatch(version)
        and version_source == "ai_content"
        and version_confidence in {"high", "medium"}
    ):
        safe_version_source = "ai_content"
        safe_version_confidence = cast(Confidence, version_confidence)
        version_reason = "AI 根据正文与可用元数据建议版本"
    else:
        version = "V1"
        safe_version_source = "default_needs_confirmation"
        safe_version_confidence = "low"
        version_reason = "未能可靠判断版本，已使用规则默认值"

    level = ai.suggested_confidentiality_level if ai else None
    confidentiality_source = ai.confidentiality_source if ai else None
    confidentiality_confidence = ai.confidentiality_confidence if ai else None
    if (
        level in _LEVELS
        and confidentiality_source == "ai_content"
        and confidentiality_confidence in {"high", "medium"}
    ):
        safe_level = ConfidentialityLevel(level)
        safe_confidentiality_source: ConfidentialitySource = "ai_content"
        safe_confidentiality_confidence: Confidence = cast(Confidence, confidentiality_confidence)
        # Only return a server-owned summary. Never project stored model prose.
        confidentiality_reason = f"AI 根据正文内容特征建议为 {safe_level.value}"
    else:
        safe_level = ConfidentialityLevel.L2
        safe_confidentiality_source = "default_needs_confirmation"
        safe_confidentiality_confidence = "low"
        confidentiality_reason = "AI 未能可靠判断内容密级，已使用规则默认值"
    return {
        "suggested_version": version,
        "version_source": safe_version_source,
        "version_confidence": safe_version_confidence,
        "version_reason": version_reason[:300],
        "suggested_confidentiality_level": safe_level,
        "confidentiality_source": safe_confidentiality_source,
        "confidentiality_confidence": safe_confidentiality_confidence,
        "confidentiality_reason": confidentiality_reason[:300],
    }
