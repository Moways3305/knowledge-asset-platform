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

    suggested_version: str | None
    version_source: VersionSource | None
    version_confidence: Confidence | None
    version_reason: str | None
    suggested_confidentiality_level: ConfidentialityLevel | None
    confidentiality_source: ConfidentialitySource | None
    confidentiality_confidence: Confidence | None
    confidentiality_reason: str | None


class NamingPreviewAdvice(TypedDict):
    """Non-null naming defaults required by the confirmation-preview DTO."""

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
    candidate_version = (ai.suggested_version or "").upper() if ai else ""
    version: str | None
    version_source = ai.version_source if ai else None
    version_confidence = ai.version_confidence if ai else None
    safe_version_source: VersionSource | None
    safe_version_confidence: Confidence | None
    if (
        _VERSION.fullmatch(candidate_version)
        and version_source == "source_filename"
        and version_confidence == "high"
    ):
        version = candidate_version
        safe_version_source = "source_filename"
        safe_version_confidence = "high"
        version_reason = "从源文件名识别到标准版本"
    elif (
        _VERSION.fullmatch(candidate_version)
        and version_source == "ai_content"
        and version_confidence in {"high", "medium"}
    ):
        version = candidate_version
        safe_version_source = "ai_content"
        safe_version_confidence = cast(Confidence, version_confidence)
        version_reason = "AI 根据正文与可用元数据建议版本"
    else:
        version = None
        safe_version_source = None
        safe_version_confidence = None
        version_reason = None

    level = ai.suggested_confidentiality_level if ai else None
    confidentiality_source = ai.confidentiality_source if ai else None
    confidentiality_confidence = ai.confidentiality_confidence if ai else None
    safe_level: ConfidentialityLevel | None
    safe_confidentiality_source: ConfidentialitySource | None
    safe_confidentiality_confidence: Confidence | None
    if (
        level in _LEVELS
        and confidentiality_source == "ai_content"
        and confidentiality_confidence in {"high", "medium"}
    ):
        safe_level = ConfidentialityLevel(level)
        safe_confidentiality_source = "ai_content"
        safe_confidentiality_confidence = cast(Confidence, confidentiality_confidence)
        # Only return a server-owned summary. Never project stored model prose.
        confidentiality_reason = f"AI 根据正文内容特征建议为 {safe_level.value}"
    else:
        safe_level = None
        safe_confidentiality_source = None
        safe_confidentiality_confidence = None
        confidentiality_reason = None
    return {
        "suggested_version": version,
        "version_source": safe_version_source,
        "version_confidence": safe_version_confidence,
        "version_reason": version_reason[:300] if version_reason else None,
        "suggested_confidentiality_level": safe_level,
        "confidentiality_source": safe_confidentiality_source,
        "confidentiality_confidence": safe_confidentiality_confidence,
        "confidentiality_reason": confidentiality_reason[:300] if confidentiality_reason else None,
    }


def naming_preview_advice(ai: IngestTaskAiResult | None) -> NamingPreviewAdvice:
    """Provide explicit defaults for naming-confirmation previews only.

    Ingest-result endpoints must continue to expose unavailable AI advice as null.
    Naming previews instead require a confirmable baseline, so their DTO deliberately
    carries non-null defaults.
    """
    advice = safe_naming_advice(ai)
    return {
        "suggested_version": advice["suggested_version"] or "V1",
        "version_source": advice["version_source"] or "default_needs_confirmation",
        "version_confidence": advice["version_confidence"] or "low",
        "version_reason": advice["version_reason"] or "未能可靠判断版本，已使用规则默认值",
        "suggested_confidentiality_level": advice["suggested_confidentiality_level"]
        or ConfidentialityLevel.L2,
        "confidentiality_source": advice["confidentiality_source"] or "default_needs_confirmation",
        "confidentiality_confidence": advice["confidentiality_confidence"] or "low",
        "confidentiality_reason": advice["confidentiality_reason"]
        or "AI 未能可靠判断内容密级，已使用规则默认值",
    }
