"""共享底座索引机制。

把「一个 asset version 的规范 Markdown 推进 WeKnora 底座（建库+初始化+上传+回写索引状态）」收口到
一处，供 **confirm（入库确认）** 与 **retry-index（失败重试）** 共用同一安全口径：

- 资产已在业务侧落库；本模块只负责底座侧推进与 version 索引状态回写，**绝不**回滚业务资产 /
  人工校正；建库/初始化/上传失败 → version `index_status=index_failed` + 安全 error_code，可重试。
- 与 `IngestTask` 解耦：调用方负责加载并校验已持久化的规范 Markdown；本模块会拒绝原件或
  非 Markdown 字节，不提供原件回退路径。
- 安全红线：回写 / 返回**绝不**外泄 `weknora_kb_id` / `weknora_doc_id` / api_key / 原始 payload /
  storage_ref。`index_error_code` 是安全码，`index_error_message` 是安全中文文案。
- 业务审计由调用方写（confirm 写 `ingest.*`，retry 写 `knowledge.index_*`），本模块不写审计。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAssetVersion
from app.schemas.enums import KnowledgeScope
from app.services import chunking, error_catalog
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    WeKnoraDuplicateError,
    WeKnoraError,
)
from app.services.weknora_kb import resolve_or_create_kb
from app.services.weknora_model_selection import resolve_models_for_kb

_logger = logging.getLogger(__name__)


@dataclass
class IndexOutcome:
    """底座索引结果（安全字段，供调用方写审计 / 构响应）。"""

    index_status: str  # indexing | indexed | index_failed | skipped
    parse_status: str | None = None
    error_code: str | None = None
    is_duplicate: bool = False


def _governance_upload(
    file_bytes: bytes,
    source_file_name: str,
    source_file_mime: str | None,
) -> tuple[bytes, str, str | None, str | None]:
    """Fail closed unless the caller supplies a persisted canonical Markdown file."""
    if source_file_mime != "text/markdown" or not source_file_name.lower().endswith(
        ".canonical.md"
    ):
        raise WeKnoraError(
            "canonical_markdown_required",
            "知识底座只接受已确认的规范 Markdown",
        )
    try:
        governance_text = file_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WeKnoraError(
            "canonical_markdown_invalid",
            "规范 Markdown 校验失败",
        ) from exc
    if not governance_text.strip():
        raise WeKnoraError("canonical_markdown_invalid", "规范 Markdown 校验失败")
    return file_bytes, source_file_name, "text/markdown", governance_text


def _apply_parse_state(version: KnowledgeAssetVersion, parse_status: str) -> str:
    """Map provider parse truth to the KAP searchable terminal state."""
    version.weknora_parse_status = parse_status
    # A real provider response breaks the consecutive reconciliation-failure chain.
    version.index_reconcile_failure_count = 0
    version.index_last_reconcile_failed_at = None
    if parse_status in {"completed", "duplicate"}:
        version.index_status = "indexed"
        version.indexed_at = utc_now()
        version.index_error_code = None
        version.index_error_message = None
    elif parse_status == "failed":
        version.index_status = "index_failed"
        version.indexed_at = None
        version.index_error_code = "weknora_parse_failed"
        version.index_error_message = error_catalog.user_message("weknora_parse_failed")
    else:
        version.index_status = "indexing"
        version.indexed_at = None
        version.index_error_code = None
        version.index_error_message = None
    return version.index_status


async def _rebuild_chunks_best_effort(
    session: AsyncSession,
    *,
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    governance_text: str,
) -> None:
    """索引成功后重建版本 chunk 注册表；失败只告警，不回滚已成功的索引。"""
    try:
        await chunking.rebuild_version_chunks(
            session,
            asset_id=asset_id,
            version_id=version_id,
            governance_text=governance_text,
        )
        await session.commit()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("chunk_rebuild_failed", exc_info=exc)
        await session.rollback()


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
    embedding_model_ref: str | None = None,
    rerank_model_ref: str | None = None,
) -> IndexOutcome:
    """建库+初始化（resolve_or_create_kb）+ 上传规范 Markdown + 回写真实索引状态。

    受理 → ("indexing", parse_status)；终态成功/409 重复 → indexed；
    建库/初始化/上传失败 → ("index_failed", None, error_code)。**绝不回滚已落库资产。**
    """
    try:
        models = await resolve_models_for_kb(
            session,
            weknora,
            embedding_model_ref=embedding_model_ref,
            rerank_model_ref=rerank_model_ref,
            trace_id=trace_id,
        )
        kb_id = await resolve_or_create_kb(
            session,
            weknora,
            scope=scope,
            owner_user_id=owner_user_id if scope == KnowledgeScope.personal.value else None,
            project_id=project_id,
            models=models,
            trace_id=trace_id,
        )
        content, upload_name, upload_mime, governance_text = _governance_upload(
            file_bytes, source_file_name, source_file_mime
        )
        data = await weknora.upload_file(
            kb_id=kb_id,
            content=content,
            file_name=upload_name,
            mime=upload_mime,
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
            index_status = _apply_parse_state(version, parse_status)
        else:
            index_status = "indexing"
        await session.commit()
        if governance_text:
            await _rebuild_chunks_best_effort(
                session,
                asset_id=asset_id,
                version_id=version_id,
                governance_text=governance_text,
            )
        return IndexOutcome(
            index_status,
            parse_status,
            "weknora_parse_failed" if index_status == "index_failed" else None,
            False,
        )
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
    embedding_model_ref: str | None = None,
    rerank_model_ref: str | None = None,
) -> IndexOutcome:
    """显式 reparse：对**已进底座但解析异常**的 version 强制刷新底座解析。

    WeKnora 无独立 reparse 端点，封装为「受控重传」（`weknora.reparse_knowledge`：删旧 doc +
    重传原文），**会更新 `weknora_doc_id` 为新 doc**。已绑定 kb 时复用其 kb_id，否则按 scope
    resolve/create。成功 → index_status 保持 indexed + 新 parse_status；失败 → index_failed
    （可再试）。**绝不回滚业务资产**，回写 / 返回不外泄 kb_id / doc_id / api_key / storage_ref。
    """
    version = await _load_version(session, version_id)
    kb_id = version.weknora_kb_id if version is not None else None
    knowledge_id = version.weknora_doc_id if version is not None else None
    try:
        if not kb_id:
            models = await resolve_models_for_kb(
                session,
                weknora,
                embedding_model_ref=embedding_model_ref,
                rerank_model_ref=rerank_model_ref,
                trace_id=trace_id,
            )
            kb_id = await resolve_or_create_kb(
                session,
                weknora,
                scope=scope,
                owner_user_id=owner_user_id if scope == KnowledgeScope.personal.value else None,
                project_id=project_id,
                models=models,
                trace_id=trace_id,
            )
        content, upload_name, upload_mime, governance_text = _governance_upload(
            file_bytes, source_file_name, source_file_mime
        )
        data = await weknora.reparse_knowledge(
            kb_id=kb_id,
            knowledge_id=knowledge_id,
            content=content,
            file_name=upload_name,
            mime=upload_mime,
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
            index_status = _apply_parse_state(version, parse_status)
        else:
            index_status = "indexing"
        await session.commit()
        if governance_text:
            await _rebuild_chunks_best_effort(
                session,
                asset_id=asset_id,
                version_id=version_id,
                governance_text=governance_text,
            )
        return IndexOutcome(
            index_status,
            parse_status,
            "weknora_parse_failed" if index_status == "index_failed" else None,
            False,
        )
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
