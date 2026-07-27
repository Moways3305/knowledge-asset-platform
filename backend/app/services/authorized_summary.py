"""Authorized summary construction for confidentiality levels that require redaction."""

from __future__ import annotations

from app.services.desensitization import (
    DesensitizationEngine,
    RuleBasedDesensitizer,
)

REDACTED_SUMMARY_PREFIX = "（脱敏）"
ONE_LINER_MAX_CHARS = 200


def _redact(
    text: str,
    *,
    desensitizer: DesensitizationEngine,
) -> str | None:
    """Return prefixed, rule-redacted text, failing closed when redaction cannot run."""
    normalized = text.strip()
    if not normalized:
        return None
    result = desensitizer.desensitize(normalized)
    if result.status in {"failed", "skipped"} or not result.text.strip():
        return None
    safe = result.text.strip()
    if safe.startswith(REDACTED_SUMMARY_PREFIX):
        return safe
    return f"{REDACTED_SUMMARY_PREFIX}{safe}"


def build_authorized_summary_variants(
    *,
    one_liner: str | None,
    detailed: str,
    desensitizer: DesensitizationEngine | None = None,
) -> tuple[str | None, str | None]:
    """Build distinct short and detailed redacted variants.

    The detailed variant is never length-truncated. The one-liner preserves its short semantic
    contract and falls back to a bounded prefix of the detailed source only when no one-liner was
    supplied.
    """
    engine = desensitizer or RuleBasedDesensitizer()
    detailed_source = detailed.strip()
    short_source = (one_liner or "").strip() or detailed_source[:ONE_LINER_MAX_CHARS]
    return (
        _redact(short_source[:ONE_LINER_MAX_CHARS], desensitizer=engine),
        _redact(detailed_source, desensitizer=engine),
    )
