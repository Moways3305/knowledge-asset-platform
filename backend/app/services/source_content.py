"""受控源文件正文读取。

只在后端按资产版本解析入库任务的 server-only 存储引用，读取字节后复用集中抽取入口。
返回值只包含正文和有限安全状态；调用方不得记录正文、文件名、存储引用或底层异常。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAssetVersion
from app.services.extraction import extract_text
from app.services.storage import LocalFileStorage, StorageError

CONTENT_MESSAGES = {
    "available": "正文可读取。",
    "empty": "源文件存在，但未提取到可读文本。",
    "source_unavailable": "当前版本的受控源文件不可用。",
    "extraction_unsupported": "当前文件格式不支持自动提取。",
    "extraction_failed": "当前文件正文提取失败。",
    "parse_pending": "当前版本仍在解析中，且暂时没有可用源文件。",
    "parse_failed": "上游解析失败，且当前版本源文件不可用。",
}


@dataclass(frozen=True)
class SourceContent:
    text: str
    status: str

    @property
    def available(self) -> bool:
        return self.status == "available"

    @property
    def message(self) -> str:
        return CONTENT_MESSAGES[self.status]


def _unavailable_status(parse_status: str | None) -> str:
    if parse_status == "failed":
        return "parse_failed"
    if parse_status in {"pending", "processing"}:
        return "parse_pending"
    return "source_unavailable"


async def resolve_version_source_task(
    session: AsyncSession,
    *,
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
) -> IngestTask | None:
    task = (
        (
            await session.execute(
                select(IngestTask)
                .where(
                    IngestTask.result_asset_id == asset_id,
                    IngestTask.result_version_id == version_id,
                    IngestTask.source_file_ref.is_not(None),
                )
                .order_by(IngestTask.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )
    if task is not None:
        return task

    # 滚动升级/极早期测试数据兼容：仅当该资产确实只有一个版本时，才允许使用尚未
    # 回填 result_version_id 的唯一历史任务。多版本资产绝不按时间“猜”源文件。
    version_count = int(
        (
            await session.execute(
                select(func.count())
                .select_from(KnowledgeAssetVersion)
                .where(KnowledgeAssetVersion.asset_id == asset_id)
            )
        ).scalar()
        or 0
    )
    if version_count != 1:
        return None
    return (
        (
            await session.execute(
                select(IngestTask)
                .where(
                    IngestTask.result_asset_id == asset_id,
                    IngestTask.result_version_id.is_(None),
                    IngestTask.source_file_ref.is_not(None),
                )
                .order_by(IngestTask.created_at.desc())
                .limit(1)
            )
        )
        .scalars()
        .first()
    )


async def extract_current_version_text(
    session: AsyncSession,
    storage: LocalFileStorage,
    *,
    asset_id: uuid.UUID,
    version: KnowledgeAssetVersion | None,
) -> SourceContent:
    """读取指定当前版本的受控源文件并抽取全文，错误仅映射为安全有限状态。"""
    if version is None:
        return SourceContent(text="", status="source_unavailable")
    task = await resolve_version_source_task(session, asset_id=asset_id, version_id=version.id)
    if task is None:
        return SourceContent(text="", status=_unavailable_status(version.weknora_parse_status))
    try:
        content = storage.resolve_path(task.source_file_ref).read_bytes()
    except (OSError, StorageError, ValueError):
        return SourceContent(text="", status=_unavailable_status(version.weknora_parse_status))

    result = extract_text(
        content,
        file_name=task.source_file_name,
        mime=task.source_file_mime_type,
    )
    status = {
        "extracted": "available",
        "empty": "empty",
        "unsupported": "extraction_unsupported",
        "failed": "extraction_failed",
    }.get(result.status, "extraction_failed")
    return SourceContent(text=result.text if status == "available" else "", status=status)
