"""Shared upload-session constraints, value objects, and pure validation helpers."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from app.models.ingest import (
    IngestTask,
)
from app.schemas.enums import IngestSource, IngestStatus
from app.schemas.permission import CallerContext

BATCH_SIZE = 200
TRANSPORT_BATCH_MAX_FILES = 10
TRANSPORT_BATCH_MAX_BYTES = 20 * 1024 * 1024
SINGLE_FILE_MAX_BYTES = 25 * 1024 * 1024
_PENDING_NAME_WARNING_STATUSES = {
    IngestStatus.pending_confirmation.value,
    IngestStatus.failed.value,
    IngestStatus.rejected.value,
    IngestStatus.waiting_review.value,
}
MACOS_METADATA_MESSAGE = "这是 macOS 元数据文件，不是原始资料；请选择不带 `._` 前缀的原文件"
UNREADABLE_FILE_MESSAGE = "文件内容当前不可读取；请先在本机完成下载后重新选择"
PROCESSING_MAX_AGE = timedelta(hours=2)
PROCESSING_ACTIVITY_GRACE = timedelta(minutes=15)

# 文件名日期识别：YYYYMMDD、YYYY-MM-DD、YYYY/MM/DD、YYYY年M月D日 等形态。
_FILENAME_DATE_RE = re.compile(r"(?<!\d)(\d{4})[-_.年/]?(\d{1,2})[-_.月/]?(\d{1,2})日?(?!\d)")


@dataclass(frozen=True)
class UploadCandidate:
    file_name: str
    file_size: int
    file_type: str | None
    storage_ref: str | None = None
    content_hash: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    # 文件形成日期建议（YYYY-MM-DD，客户端 lastModified 或文件名正则兜底）。
    suggested_formed_on: str | None = None


def extract_formed_on_from_filename(file_name: str) -> str | None:
    """从文件名提取日期（YYYY-MM-DD）；提取不到或日期非法 → None。

    只做确定性正则 + 日历合法性校验，不猜语义（如 2026-13-99 判非法）。
    """
    match = _FILENAME_DATE_RE.search(file_name or "")
    if not match:
        return None
    try:
        year, month, day = (int(g) for g in match.groups())
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        return f"{year:04d}-{month:02d}-{day:02d}"
    except (TypeError, ValueError):
        return None


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _display_name(value: str) -> str:
    """Keep a display basename, never a client absolute/relative path."""
    cleaned = "".join(char for char in value if ord(char) >= 32 and ord(char) != 127)
    return (cleaned.replace("\\", "/").rsplit("/", 1)[-1].strip() or "file")[:500]


def macos_metadata_error(value: str) -> str | None:
    """Recognize only explicit macOS/archive metadata patterns."""
    normalized = value.replace("\\", "/")
    segments = [segment for segment in normalized.split("/") if segment]
    basename = segments[-1] if segments else normalized
    if (
        basename.startswith("._")
        or basename.casefold() == ".ds_store"
        or any(segment.casefold() == "__macosx" for segment in segments[:-1])
    ):
        return MACOS_METADATA_MESSAGE
    return None


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _is_stale_processing(task: IngestTask, now: datetime) -> bool:
    return (
        task.source == IngestSource.path_b_upload.value
        and task.status == IngestStatus.processing.value
        and task.result_asset_id is None
        and _aware(task.created_at) <= now - PROCESSING_MAX_AGE
        and _aware(task.updated_at) <= now - PROCESSING_ACTIVITY_GRACE
    )


def _normalized_name(value: str) -> str:
    return unicodedata.normalize("NFKC", _display_name(value)).casefold().strip()


def stable_batch_sizes(total: int) -> list[int]:
    """Pure batching contract used by migrations/tests/UI evidence."""
    if total <= 0:
        return []
    return [min(BATCH_SIZE, total - start) for start in range(0, total, BATCH_SIZE)]


def authorize_create(caller: CallerContext) -> None:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可发起入库")
