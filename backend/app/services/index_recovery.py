"""索引中断判定与安全恢复文案的单一口径。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.models.knowledge import KnowledgeAssetVersion

INTERRUPTED_ERROR_CODE = "index_interrupted"


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def minimum_age_minutes() -> int:
    return max(1, int(get_settings().index_interrupted_min_age_minutes))


def required_failure_count() -> int:
    return max(2, int(get_settings().index_interrupted_reconcile_failures))


def is_old_enough(version: KnowledgeAssetVersion, *, now: datetime) -> bool:
    started_at = version.activated_at or version.created_at
    return _aware(started_at) <= _aware(now) - timedelta(minutes=minimum_age_minutes())


def should_mark_interrupted(version: KnowledgeAssetVersion, *, now: datetime) -> bool:
    return (
        version.index_status == "indexing"
        and version.weknora_parse_status in {"pending", "processing"}
        and is_old_enough(version, now=now)
        and version.index_reconcile_failure_count >= required_failure_count()
    )


def recovery_state(index_status: str, error_code: str | None) -> str:
    if index_status == "index_failed" and error_code == INTERRUPTED_ERROR_CODE:
        return "interrupted"
    if index_status == "index_failed":
        return "failed"
    if index_status == "not_indexed":
        return "waiting"
    if index_status == "skipped":
        return "skipped"
    if index_status == "indexing":
        return "processing"
    return "searchable" if index_status == "indexed" else "unknown"
