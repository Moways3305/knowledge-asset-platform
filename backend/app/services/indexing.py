"""共享底座索引机制。

把「一个 asset version 的原文推进 WeKnora 底座（建库+初始化+上传+回写索引状态）」收口到
一处，供 **confirm（入库确认）** 与 **retry-index（失败重试）** 共用同一安全口径：

- 资产已在业务侧落库；本模块只负责底座侧推进与 version 索引状态回写，**绝不**回滚业务资产 /
  人工校正；建库/初始化/上传失败 → version `index_status=index_failed` + 安全 error_code，可重试。
- 与 `IngestTask` 解耦：调用方负责加载原文字节（confirm 从 task.source_file_ref，retry 从其入库
  任务的 source_file_ref），本模块只收 `file_bytes` + 安全文件元数据。
- 安全红线：回写 / 返回**绝不**外泄 `weknora_kb_id` / `weknora_doc_id` / api_key / 原始 payload /
  storage_ref。`index_error_code` 是安全码，`index_error_message` 是安全中文文案。
- 业务审计由调用方写（confirm 写 `ingest.*`，retry 写 `knowledge.index_*`），本模块不写审计。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAssetVersion
from app.schemas.enums import KnowledgeScope
from app.services import error_catalog
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    WeKnoraDuplicateError,
    WeKnoraError,
)
from app.services.weknora_kb import resolve_or_create_kb


@dataclass
class IndexOutcome:
    """底座索引结果（安全字段，供调用方写审计 / 构响应）。"""

    index_status: str  # indexed | index_failed | skipped
    parse_status: str | None = None
    error_code: str | None = None
    is_duplicate: bool = False


async def _load_version(
    session: AsyncSession, version_id: uuid.UUID
) -> KnowledgeAssetVersion | None:
    return (
        await session.execute(
            select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id == version_id)
        )
    ).scalar_one_or_none()


async def mark_index_failed(
    session: AsyncSession,
    *,
    version_id: uuid.UUID,
    error_code: str,
) -> IndexOutcome:
    """把某 version 标记为 index_failed（资产保留）。先 rollback 丢弃脏写，再以干净状态回写 + 提交。

    回写：原始安全 `index_error_code` + 中央目录派生的**用户态**安全文案。
    绝不含 kb_id / doc_id / api_key / 原始 payload / 上游 message。
    """
    # 归一为安全目录 code（上游 code 也不可信，可能含 sk-/url/真实 id）：DB 只存安全 code。
    code = error_catalog.safe_code(error_code)
    await session.rollback()
    version = await _load_version(session, version_id)
    if version is not None:
        version.index_status = "index_failed"
        version.index_error_code = code
        # 持久化用户态文案。
        version.index_error_message = error_catalog.user_message(code)
        version.weknora_parse_status = version.weknora_parse_status or "failed"
    await session.commit()
    return IndexOutcome("index_failed", None, code, False)


async def index_asset_version(
    session: AsyncSession,
    weknora: WeKnoraClient | NullWeKnoraClient,
    *,
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    scope: str,
    owner_user_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    confidentiality: str,
    file_bytes: bytes,
    source_file_name: str,
    source_file_mime: str | None,
    channel: str | None,
    trace_id: str | None,
) -> IndexOutcome:
    """建库+初始化（resolve_or_create_kb）+ 上传原文 + 回写 version 索引状态。提交后返回 outcome。

    成功 → ("indexed", parse_status)；409 重复 → ("indexed", "duplicate", is_duplicate=True)；
    建库/初始化/上传失败 → ("index_failed", None, error_code)。**绝不回滚已落库资产。**
    """
    from app.core.config import get_settings

    try:
        kb_id = await resolve_or_create_kb(
            session,
            weknora,
            scope=scope,
            owner_user_id=owner_user_id if scope == KnowledgeScope.personal.value else None,
            project_id=project_id,
            embedding_model_id=get_settings().weknora_embedding_model_id,
            trace_id=trace_id,
        )
        data = await weknora.upload_file(
            kb_id=kb_id,
            content=file_bytes,
            file_name=source_file_name,
            mime=source_file_mime,
            metadata={
                "asset_id": str(asset_id),
                "version_id": str(version_id),
                "scope": scope,
                "confidentiality_level": confidentiality,
            },
            channel=channel,
            trace_id=trace_id,
        )
        version = await _load_version(session, version_id)
        parse_status = str(data.get("parse_status") or "processing")
        if version is not None:
            version.weknora_kb_id = kb_id
            version.weknora_doc_id = str(data.get("id") or "") or None
            version.weknora_parse_status = parse_status
            version.index_status = "indexed"
            version.indexed_at = utc_now()
            version.index_error_code = None
            version.index_error_message = None
        await session.commit()
        return IndexOutcome("indexed", parse_status, None, False)
    except WeKnoraDuplicateError as dup:
        # 内容已在底座（file_hash 409）：复用既有 doc，算索引成功。kb_id 已在 resolve 后绑定。
        version = await _load_version(session, version_id)
        if version is not None:
            version.weknora_kb_id = kb_id
            version.weknora_doc_id = dup.existing_knowledge_id
            version.weknora_parse_status = "duplicate"
            version.index_status = "indexed"
            version.indexed_at = utc_now()
            version.index_error_code = None
            version.index_error_message = None
        await session.commit()
        return IndexOutcome("indexed", "duplicate", None, True)
    except (WeKnoraError, OSError) as exc:
        code = getattr(exc, "code", None) or "weknora_index_failed"
        return await mark_index_failed(session, version_id=version_id, error_code=str(code))


async def reparse_asset_version(
    session: AsyncSession,
    weknora: WeKnoraClient | NullWeKnoraClient,
    *,
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    scope: str,
    owner_user_id: uuid.UUID | None,
    project_id: uuid.UUID | None,
    confidentiality: str,
    file_bytes: bytes,
    source_file_name: str,
    source_file_mime: str | None,
    channel: str | None,
    trace_id: str | None,
) -> IndexOutcome:
    """显式 reparse：对**已进底座但解析异常**的 version 强制刷新底座解析。

    WeKnora 无独立 reparse 端点，封装为「受控重传」（`weknora.reparse_knowledge`：删旧 doc +
    重传原文），**会更新 `weknora_doc_id` 为新 doc**。已绑定 kb 时复用其 kb_id，否则按 scope
    resolve/create。成功 → index_status 保持 indexed + 新 parse_status；失败 → index_failed
    （可再试）。**绝不回滚业务资产**，回写 / 返回不外泄 kb_id / doc_id / api_key / storage_ref。
    """
    from app.core.config import get_settings

    version = await _load_version(session, version_id)
    kb_id = version.weknora_kb_id if version is not None else None
    knowledge_id = version.weknora_doc_id if version is not None else None
    try:
        if not kb_id:
            kb_id = await resolve_or_create_kb(
                session,
                weknora,
                scope=scope,
                owner_user_id=owner_user_id if scope == KnowledgeScope.personal.value else None,
                project_id=project_id,
                embedding_model_id=get_settings().weknora_embedding_model_id,
                trace_id=trace_id,
            )
        data = await weknora.reparse_knowledge(
            kb_id=kb_id,
            knowledge_id=knowledge_id,
            content=file_bytes,
            file_name=source_file_name,
            mime=source_file_mime,
            metadata={
                "asset_id": str(asset_id),
                "version_id": str(version_id),
                "scope": scope,
                "confidentiality_level": confidentiality,
            },
            channel=channel,
            trace_id=trace_id,
        )
        version = await _load_version(session, version_id)
        parse_status = str(data.get("parse_status") or "processing")
        if version is not None:
            version.weknora_kb_id = kb_id
            version.weknora_doc_id = str(data.get("id") or "") or None
            version.weknora_parse_status = parse_status
            version.index_status = "indexed"
            version.indexed_at = utc_now()
            version.index_error_code = None
            version.index_error_message = None
        await session.commit()
        return IndexOutcome("indexed", parse_status, None, False)
    except WeKnoraDuplicateError as dup:
        # 删旧未生效 / 内容仍命中去重：复用既有 doc，解析标 duplicate（不算失败）。
        version = await _load_version(session, version_id)
        if version is not None:
            version.weknora_kb_id = kb_id
            version.weknora_doc_id = dup.existing_knowledge_id
            version.weknora_parse_status = "duplicate"
            version.index_status = "indexed"
            version.indexed_at = utc_now()
            version.index_error_code = None
            version.index_error_message = None
        await session.commit()
        return IndexOutcome("indexed", "duplicate", None, True)
    except (WeKnoraError, OSError) as exc:
        code = getattr(exc, "code", None) or "weknora_index_failed"
        return await mark_index_failed(session, version_id=version_id, error_code=str(code))
