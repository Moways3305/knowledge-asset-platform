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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.utils import utc_now
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.enums import KnowledgeScope
from app.services import chunking, domain_events, error_catalog
from app.services.job_execution import exclusive_execution
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    WeKnoraDuplicateError,
    WeKnoraError,
)
from app.services.weknora_kb import resolve_or_create_kb
from app.services.weknora_model_selection import resolve_models_for_kb
from app.services.weknora_parse_state import FAILED_PARSE_STATUSES, parse_error_code

_logger = logging.getLogger(__name__)


@dataclass
class IndexOutcome:
    """底座索引结果（安全字段，供调用方写审计 / 构响应）。"""

    index_status: str  # indexing | indexed | index_failed | skipped
    parse_status: str | None = None
    error_code: str | None = None
    is_duplicate: bool = False


def _exclusive_version(
    operation: Callable[..., Awaitable[IndexOutcome]],
) -> Callable[..., Awaitable[IndexOutcome]]:
    @wraps(operation)
    async def run(session: AsyncSession, weknora, **kwargs) -> IndexOutcome:
        async with exclusive_execution(session, "index-version", kwargs["version_id"]) as owned:
            if not owned:
                return IndexOutcome("indexing")
            return await operation(session, weknora, **kwargs)

    return run


async def _writable_version(
    session: AsyncSession,
    version_id: uuid.UUID,
    *,
    asset_id: uuid.UUID | None = None,
    expected_document: tuple[str | None, str | None] | None = None,
) -> KnowledgeAssetVersion | None:
    """Lock in lifecycle order and refresh identity-map entries before writing."""
    with session.no_autoflush:
        owner = await session.scalar(
            select(KnowledgeAssetVersion.asset_id).where(KnowledgeAssetVersion.id == version_id)
        )
        if owner is None or (asset_id is not None and owner != asset_id):
            return None
        asset = await session.scalar(
            select(KnowledgeAsset)
            .where(KnowledgeAsset.id == owner)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            asset is None
            or asset.asset_status == "deleted"
            or asset.deleted_at is not None
            or asset.current_version_id not in (None, version_id)
        ):
            return None
        version = await session.scalar(
            select(KnowledgeAssetVersion)
            .where(KnowledgeAssetVersion.id == version_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if version is None or version.version_status != "active":
        return None
    if (
        expected_document is not None
        and (version.weknora_kb_id, version.weknora_doc_id) != expected_document
    ):
        return None
    return version


async def _save_result(
    session: AsyncSession,
    weknora,
    *,
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    expected_document: tuple[str | None, str | None],
    kb_id: str | None,
    document_id: str | None,
    parse_status: str,
    duplicate: bool = False,
    governance_text: str | None = None,
    trace_id: str | None,
) -> IndexOutcome:
    if not kb_id:
        return await mark_index_failed(
            session,
            version_id=version_id,
            error_code="weknora_index_failed",
            expected_document=expected_document,
        )
    version = await _writable_version(
        session, version_id, asset_id=asset_id, expected_document=expected_document
    )
    if version is None:
        await session.rollback()
        # Never delete a deduplicated/shared document or one another version
        # already references. Fresh orphan uploads get the same best-effort
        # cleanup as deletion; provider failures cannot resurrect platform data.
        if document_id and not duplicate and document_id != expected_document[1]:
            referenced = await session.scalar(
                select(KnowledgeAssetVersion.id)
                .where(KnowledgeAssetVersion.weknora_doc_id == document_id)
                .limit(1)
            )
            await session.rollback()
            if referenced is None:
                try:
                    await weknora.delete_knowledge(document_id, trace_id=trace_id)
                except Exception as exc:
                    _logger.warning(
                        "stale_index_cleanup_failed", extra={"error_type": type(exc).__name__}
                    )
        return IndexOutcome("skipped")
    version.weknora_kb_id = kb_id
    version.weknora_doc_id = document_id
    status = _apply_parse_state(version, parse_status)
    await _publish_index_status(session, version=version, status=status)
    await session.commit()
    if governance_text:
        await _rebuild_chunks_best_effort(
            session, asset_id=asset_id, version_id=version_id, governance_text=governance_text
        )
    return IndexOutcome(
        status,
        parse_status,
        parse_error_code(parse_status) if status == "index_failed" else None,
        duplicate,
    )


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
    elif parse_status in FAILED_PARSE_STATUSES:
        version.index_status = "index_failed"
        version.indexed_at = None
        version.index_error_code = parse_error_code(parse_status)
        version.index_error_message = error_catalog.user_message(version.index_error_code)
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
        if await _writable_version(session, version_id, asset_id=asset_id) is None:
            await session.rollback()
            return
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


async def _publish_index_status(
    session: AsyncSession,
    *,
    version: KnowledgeAssetVersion | None,
    status: str,
) -> None:
    if version is None:
        return
    asset = await session.get(KnowledgeAsset, version.asset_id)
    await domain_events.publish(
        session,
        domain_events.DomainEvent(
            event_type=domain_events.INDEX_STATUS_CHANGED,
            aggregate_type="knowledge_asset_version",
            aggregate_id=version.id,
            payload=domain_events.safe_payload(
                asset_id=version.asset_id,
                version_id=version.id,
                project_id=asset.project_id if asset is not None else None,
                status=status,
            ),
            idempotency_key=f"index-status:{version.id}:{status}",
        ),
    )


async def mark_index_failed(
    session: AsyncSession,
    *,
    version_id: uuid.UUID,
    error_code: str,
    expected_document: tuple[str | None, str | None] | None = None,
) -> IndexOutcome:
    """把某 version 标记为 index_failed（资产保留）。先 rollback 丢弃脏写，再以干净状态回写 + 提交。

    回写：原始安全 `index_error_code` + 中央目录派生的**用户态**安全文案。
    绝不含 kb_id / doc_id / api_key / 原始 payload / 上游 message。
    """
    # 归一为安全目录 code（上游 code 也不可信，可能含 sk-/url/真实 id）：DB 只存安全 code。
    code = error_catalog.safe_code(error_code)
    await session.rollback()
    version = await _writable_version(session, version_id, expected_document=expected_document)
    if version is None:
        await session.rollback()
        return IndexOutcome("skipped")
    version.index_status = "index_failed"
    version.index_error_code = code
    # 持久化用户态文案。
    version.index_error_message = error_catalog.user_message(code)
    version.weknora_parse_status = version.weknora_parse_status or "failed"
    await _publish_index_status(session, version=version, status="index_failed")
    await session.commit()
    return IndexOutcome("index_failed", None, code, False)


@_exclusive_version
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
    current = await _writable_version(session, version_id, asset_id=asset_id)
    if current is None:
        await session.rollback()
        return IndexOutcome("skipped")
    expected_document = (current.weknora_kb_id, current.weknora_doc_id)
    await session.commit()
    kb_id = None
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
        current_version = await _load_version(session, version_id)
        retry_existing = bool(
            current_version is not None
            and current_version.weknora_doc_id
            and current_version.weknora_kb_id == kb_id
            and current_version.weknora_parse_status in FAILED_PARSE_STATUSES
        )
        upload = weknora.reparse_knowledge if retry_existing else weknora.upload_file
        retry_args: dict[str, Any] = (
            {"knowledge_id": current_version.weknora_doc_id}
            if retry_existing and current_version is not None
            else {}
        )
        await session.commit()
        data = await upload(
            **retry_args,
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
        parse_status = str(data.get("parse_status") or "processing")
        return await _save_result(
            session,
            weknora,
            asset_id=asset_id,
            version_id=version_id,
            expected_document=expected_document,
            kb_id=kb_id,
            document_id=str(data.get("id") or "") or None,
            parse_status=parse_status,
            governance_text=governance_text,
            trace_id=trace_id,
        )
    except WeKnoraDuplicateError as dup:
        # 内容已在底座（file_hash 409）：复用既有 doc，算索引成功。kb_id 已在 resolve 后绑定。
        return await _save_result(
            session,
            weknora,
            asset_id=asset_id,
            version_id=version_id,
            expected_document=expected_document,
            kb_id=kb_id,
            document_id=dup.existing_knowledge_id,
            parse_status="duplicate",
            duplicate=True,
            trace_id=trace_id,
        )
    except (WeKnoraError, OSError) as exc:
        code = getattr(exc, "code", None) or "weknora_index_failed"
        return await mark_index_failed(
            session,
            version_id=version_id,
            error_code=str(code),
            expected_document=expected_document,
        )


@_exclusive_version
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

    使用当前规范 Markdown 受控重传。底座确认旧文档删除完成后才上传，
    避免 v0.9.0 异步删除与去重之间的竞态；解析完成前保持处理中。
    不回滚业务资产，不外泄底座标识与凭据。
    """
    version = await _writable_version(session, version_id, asset_id=asset_id)
    if version is None:
        await session.rollback()
        return IndexOutcome("skipped")
    kb_id, knowledge_id = version.weknora_kb_id, version.weknora_doc_id
    expected_document = (kb_id, knowledge_id)
    await session.commit()
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
        parse_status = str(data.get("parse_status") or "processing")
        return await _save_result(
            session,
            weknora,
            asset_id=asset_id,
            version_id=version_id,
            expected_document=expected_document,
            kb_id=kb_id,
            document_id=str(data.get("id") or "") or None,
            parse_status=parse_status,
            governance_text=governance_text,
            trace_id=trace_id,
        )
    except WeKnoraDuplicateError as dup:
        # 删旧未生效 / 内容仍命中去重：复用既有 doc，解析标 duplicate（不算失败）。
        return await _save_result(
            session,
            weknora,
            asset_id=asset_id,
            version_id=version_id,
            expected_document=expected_document,
            kb_id=kb_id,
            document_id=dup.existing_knowledge_id,
            parse_status="duplicate",
            duplicate=True,
            trace_id=trace_id,
        )
    except (WeKnoraError, OSError) as exc:
        code = getattr(exc, "code", None) or "weknora_index_failed"
        return await mark_index_failed(
            session,
            version_id=version_id,
            error_code=str(code),
            expected_document=expected_document,
        )
