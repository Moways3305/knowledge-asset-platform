"""Knowledge deletion and index-retry command workflows."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetVersion,
)
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
)
from app.schemas.knowledge import (
    KnowledgeDeleteResponse,
    RetryIndexResponse,
)
from app.schemas.permission import (
    AccessLayer,
    CallerContext,
)
from app.services import audit as audit_service
from app.services import (
    error_catalog,
    indexing,
    knowledge_lifecycle,
)
from app.services.knowledge_projection import (
    _DELETED_STATUS,
    _RETRYABLE_INDEX_STATUSES,
    _denied,
    can_retry_index,
)
from app.services.permission import (
    decide,
)
from app.services.storage import LocalFileStorage
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    weknora_enabled,
)


async def delete_asset(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    *,
    reason: str | None,
    weknora: WeKnoraClient | NullWeKnoraClient,
    trace_id: str,
) -> KnowledgeDeleteResponse:
    """Compatibility facade for the lifecycle command boundary."""
    return await knowledge_lifecycle.delete_asset(
        session,
        caller,
        asset_id,
        reason=reason,
        weknora=weknora,
        trace_id=trace_id,
        weknora_is_enabled=weknora_enabled,
    )


async def _audit_retry_failed(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    error_code: str | None,
    trace_id: str,
    project_id: uuid.UUID | None,
) -> None:
    """重试后底座仍失败的审计（exception）。extra 只放安全 stage + error_code。"""
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.exception,
        action=AuditAction.knowledge_index_retry_failed.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset_id,
        severity=AlertSeverity.warning,
        risk_level=AuditRiskLevel.high.value,
        # 审计 extra 只写安全目录 code，不写上游原始 code。
        extra={
            "failure_stage": "weknora_index_retry",
            "error_code": error_catalog.safe_code(error_code),
        },
        project_id=project_id,
    )
    await session.commit()


async def retry_index(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    *,
    weknora: WeKnoraClient | NullWeKnoraClient,
    storage: LocalFileStorage,
    trace_id: str,
    embedding_model_ref: str | None = None,
    rerank_model_ref: str | None = None,
) -> RetryIndexResponse:
    """对 index_failed / not_indexed / skipped 的资产重试底座索引。

    复用 `indexing.index_asset_version` 与 confirm 同一安全机制：资产已落库，重试只推进底座、
    回写 version 索引状态；失败仍 index_failed（可再试）。权限同 `_can_retry_index`；纯 admin /
    无权者被拒。**绝不**外泄 kb_id / doc_id / api_key / storage_ref / 原文。
    """
    asset = (
        await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))
    ).scalar_one_or_none()
    not_found = _denied(404, "knowledge_asset_not_found", "知识资产不存在或不可见")
    if asset is None or asset.asset_status == _DELETED_STATUS:
        raise not_found
    if not can_retry_index(caller, asset):
        # 不可发现 → 404 不泄露；可发现但无重试权 → 403（纯 admin 单独提示）。
        if not decide(caller, asset, AccessLayer.discovery).allowed:
            raise not_found
        if not caller.is_business_user:
            raise _denied(403, "admin_business_permission_denied", "系统管理员不具备业务索引重试权")
        raise _denied(403, "knowledge_index_retry_forbidden", "无权重试该资产的底座索引")

    version = (
        await session.execute(
            select(KnowledgeAssetVersion)
            .where(KnowledgeAssetVersion.asset_id == asset_id)
            .where(KnowledgeAssetVersion.version_status == "active")
        )
    ).scalar_one_or_none()
    if version is None:
        raise _denied(409, "knowledge_index_no_active_version", "资产无 active 版本，无法重试索引")
    if version.index_status == "indexed":
        raise _denied(409, "knowledge_index_already_indexed", "该资产已索引，无需重试")
    if version.index_status not in _RETRYABLE_INDEX_STATUSES:
        # 例如 indexing 进行中：不重复触发。
        raise _denied(409, "knowledge_index_not_retryable", "当前索引状态不可重试")

    # 捕获安全字段（后续 index_asset_version 失败路径 rollback 会使 ORM 对象过期）。
    version_id = version.id
    scope = asset.scope
    owner_user_id = asset.owner_user_id
    confidentiality = asset.confidentiality_level
    project_id = asset.project_id
    from_status = version.index_status

    # 发起审计（operation）。
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.knowledge_index_retry_requested.value,
        trace_id=trace_id,
        target_type="knowledge_asset",
        target_id=asset_id,
        extra={"scope": scope, "from_index_status": from_status},
        project_id=project_id,
    )
    await session.commit()

    # 底座未配置：标 skipped 返回（不伪装 indexed，不写失败审计）。
    # 清理上一轮失败残留：避免"已跳过索引"还混搭旧 index_error_* / parse=failed 的脏状态。
    if not weknora_enabled():
        v = (
            await session.execute(
                select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id == version_id)
            )
        ).scalar_one_or_none()
        if v is not None:
            v.index_status = "skipped"
            v.index_error_code = None
            v.index_error_message = None
            # 底座未启用的 skipped 不应保留旧解析失败态（skipped 表示"未推进底座"，无解析进度可言）。
            v.weknora_parse_status = None
        await session.commit()
        return RetryIndexResponse(
            asset_id=asset_id,
            index_status="skipped",
            weknora_parse_status=None,
            index_error_code=None,
            index_error_message=None,
            trace_id=trace_id,
        )

    try:
        from app.services.canonical_markdown import ensure_version_markdown

        markdown = await ensure_version_markdown(
            session,
            storage,
            asset_id=asset_id,
            version_id=version_id,
        )
    except Exception as exc:
        outcome = await indexing.mark_index_failed(
            session,
            version_id=version_id,
            error_code=getattr(exc, "code", "canonical_markdown_unavailable"),
        )
        await _audit_retry_failed(
            session, caller, asset_id, outcome.error_code, trace_id, project_id
        )
        return await _retry_response(session, asset_id, version_id, outcome, trace_id)

    outcome = await indexing.index_asset_version(
        session,
        weknora,
        asset_id=asset_id,
        version_id=version_id,
        scope=scope,
        owner_user_id=owner_user_id,
        project_id=project_id,
        confidentiality=confidentiality,
        file_bytes=markdown.content,
        source_file_name=markdown.file_name,
        source_file_mime=markdown.mime,
        channel=markdown.channel,
        trace_id=trace_id,
        embedding_model_ref=embedding_model_ref,
        rerank_model_ref=rerank_model_ref,
    )
    if outcome.index_status in {"indexed", "indexing"}:
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.knowledge_index_retried.value,
            trace_id=trace_id,
            target_type="knowledge_asset",
            target_id=asset_id,
            extra={
                "scope": scope,
                "parse_status": outcome.parse_status,
                "is_duplicate": outcome.is_duplicate,
            },
            project_id=project_id,
        )
        await session.commit()
    else:
        await _audit_retry_failed(
            session, caller, asset_id, outcome.error_code, trace_id, project_id
        )
    return await _retry_response(session, asset_id, version_id, outcome, trace_id)


async def _retry_response(
    session: AsyncSession,
    asset_id: uuid.UUID,
    version_id: uuid.UUID,
    outcome: indexing.IndexOutcome,
    trace_id: str,
) -> RetryIndexResponse:
    """从 outcome + 最新 version 状态构建安全重试响应（不含 kb/doc id）。"""
    v = (
        await session.execute(
            select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id == version_id)
        )
    ).scalar_one_or_none()
    safe = error_catalog.safe_code(outcome.error_code) if outcome.error_code else None
    return RetryIndexResponse(
        asset_id=asset_id,
        index_status=outcome.index_status,
        weknora_parse_status=outcome.parse_status or (v.weknora_parse_status if v else None),
        # 安全目录 code：不外显上游原始 code。
        index_error_code=safe if outcome.index_status == "index_failed" else None,
        # 用户态文案按当前目录派生，不外显历史 / 上游脏文案。
        index_error_message=(
            error_catalog.user_message(safe) if outcome.index_status == "index_failed" else None
        ),
        trace_id=trace_id,
    )
