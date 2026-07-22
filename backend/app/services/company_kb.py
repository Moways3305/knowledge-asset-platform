"""公司知识库显式创建与安全状态服务。"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeAsset
from app.models.weknora import WeknoraKbMapping
from app.schemas.company_kb import CompanyKbOut
from app.schemas.enums import AuditAction, AuditLogType, CompanyRole, KnowledgeScope
from app.schemas.permission import CallerContext
from app.services import audit as audit_service
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient, WeKnoraError
from app.services.weknora_kb import resolve_or_create_kb
from app.services.weknora_model_selection import resolve_models_for_kb

DEFAULT_COMPANY_KB_NAME = "公司知识库"
_STATUS_ACTIVE = "active"


def _denied(status: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"denied_reason": reason, "message": message})


def _is_governance(caller: CallerContext) -> bool:
    return caller.is_active and bool(
        caller.active_company_roles
        & {CompanyRole.boss.value, CompanyRole.consulting_director.value}
    )


async def _find_mapping(session: AsyncSession) -> WeknoraKbMapping | None:
    return (
        await session.execute(
            select(WeknoraKbMapping).where(
                WeknoraKbMapping.scope == KnowledgeScope.company.value,
                WeknoraKbMapping.owner_user_id.is_(None),
                WeknoraKbMapping.project_id.is_(None),
            )
        )
    ).scalar_one_or_none()


def _status_out(mapping: WeknoraKbMapping | None) -> CompanyKbOut:
    if mapping is None:
        return CompanyKbOut(
            exists=False,
            availability_summary="尚未创建",
        )
    available = mapping.status == _STATUS_ACTIVE
    return CompanyKbOut(
        exists=True,
        display_name=mapping.display_name or DEFAULT_COMPANY_KB_NAME,
        status=mapping.status,
        created_at=mapping.created_at,
        available=available,
        availability_summary="可用于公司知识入库" if available else "初始化未完成，暂不可入库",
    )


def _require_read(caller: CallerContext) -> None:
    if not _is_governance(caller):
        raise _denied(403, "company_kb_governance_required", "仅总经理 / 咨询总监可查看公司知识库")


async def _require_create(session: AsyncSession, caller: CallerContext, trace_id: str) -> None:
    if _is_governance(caller):
        return
    reason = (
        "admin_business_permission_denied"
        if CompanyRole.admin.value in caller.active_company_roles
        else "company_kb_governance_required"
    )
    await audit_service.record_denied(
        session,
        caller=caller,
        log_type=AuditLogType.exception,
        action=AuditAction.config_company_kb_created.value,
        trace_id=trace_id,
        target_type="company_knowledge_base",
        extra={"denied_reason": reason, "attempted": "company_kb.create"},
    )
    raise _denied(403, reason, "仅总经理 / 咨询总监可创建公司知识库")


async def get_company_kb(session: AsyncSession, caller: CallerContext) -> CompanyKbOut:
    _require_read(caller)
    return _status_out(await _find_mapping(session))


async def create_company_kb(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    caller: CallerContext,
    *,
    display_name: str | None,
    trace_id: str,
) -> CompanyKbOut:
    """幂等创建；只有 active 映射可用于后续公司范围入库。"""
    await _require_create(session, caller, trace_id)
    existing = await _find_mapping(session)
    if existing is not None and existing.status == _STATUS_ACTIVE:
        return _status_out(existing)
    if isinstance(client, NullWeKnoraClient):
        raise _denied(503, "company_kb_unavailable", "知识库底座未配置，暂无法创建公司知识库")

    name = (display_name or "").strip() or DEFAULT_COMPANY_KB_NAME
    try:
        models = await resolve_models_for_kb(
            session,
            client,
            embedding_model_ref=None,
            rerank_model_ref=None,
            trace_id=trace_id,
        )
        await resolve_or_create_kb(
            session,
            client,
            scope=KnowledgeScope.company.value,
            owner_user_id=None,
            project_id=None,
            models=models,
            trace_id=trace_id,
            display_name=name,
        )
    except WeKnoraError as exc:
        await session.rollback()
        mapping = await _find_mapping(session)
        if mapping is None:
            await audit_service.record_event(
                session,
                caller=caller,
                log_type=AuditLogType.exception,
                action=AuditAction.config_company_kb_created.value,
                trace_id=trace_id,
                target_type="company_knowledge_base",
                extra={"result": "unavailable"},
            )
            await session.commit()
            raise _denied(503, "company_kb_unavailable", "知识库底座暂不可用，请稍后重试") from exc
        await _audit_create(session, caller, mapping, trace_id, ready=False)
        await session.commit()
        return _status_out(mapping)

    mapping = await _find_mapping(session)
    if mapping is None:
        raise RuntimeError("company kb mapping missing after ensure-create path")
    await _audit_create(session, caller, mapping, trace_id, ready=True)
    await session.commit()
    return _status_out(mapping)


async def require_company_kb_ready(session: AsyncSession) -> None:
    """公司范围入库前置闸：不得懒创建或使用 init_failed 映射。"""
    mapping = await _find_mapping(session)
    if mapping is None or mapping.status != _STATUS_ACTIVE:
        raise _denied(409, "company_kb_not_ready", "公司知识库尚未创建或初始化未完成")


async def _audit_create(
    session: AsyncSession,
    caller: CallerContext,
    mapping: WeknoraKbMapping,
    trace_id: str,
    *,
    ready: bool,
) -> None:
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation if ready else AuditLogType.exception,
        action=AuditAction.config_company_kb_created.value,
        trace_id=trace_id,
        target_type="company_knowledge_base",
        extra={"ready": ready, "status": mapping.status},
    )


def _require_boss(caller: CallerContext) -> None:
    """删除公司库仅总经理可执行：consulting_director / admin 一律拒绝。"""
    if caller.is_active and CompanyRole.boss.value in caller.active_company_roles:
        return
    raise _denied(
        403,
        "company_kb_delete_governance_only",
        "仅总经理可删除公司知识库",
    )


async def _count_company_assets(session: AsyncSession) -> int:
    """统计未删除的公司范围知识资产数量（scope=company 且 deleted_at IS NULL）。"""
    return int(
        (
            await session.execute(
                select(func.count(KnowledgeAsset.id)).where(
                    KnowledgeAsset.scope == KnowledgeScope.company.value,
                    KnowledgeAsset.deleted_at.is_(None),
                )
            )
        ).scalar()
        or 0
    )


async def delete_company_kb(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    caller: CallerContext,
    *,
    trace_id: str,
) -> None:
    """删除公司知识库：仅 boss 可执行，且前置检查公司库下无未删除资产。

    执行流程：
    1. 权限：仅 boss，consulting_director / admin 拒绝（403
       company_kb_delete_governance_only）。
    2. 前置检查：公司库下若有未删除 KnowledgeAsset（scope=company 且
       deleted_at IS NULL），返回 409 提示先清空。
    3. 执行：调 weknora_client.delete_kb 清理底座 → 删除 weknora_kb_mappings 映射行。
    4. 记审计：config_company_kb_deleted。
    """
    _require_boss(caller)
    mapping = await _find_mapping(session)
    if mapping is None:
        raise _denied(404, "company_kb_not_found", "公司知识库尚未创建")

    asset_count = await _count_company_assets(session)
    if asset_count > 0:
        raise _denied(
            409,
            "company_kb_not_empty",
            f"请先清空 {asset_count} 个公司资产后再删除公司知识库",
        )

    if isinstance(client, NullWeKnoraClient):
        raise _denied(503, "company_kb_unavailable", "知识库底座未配置，暂无法删除公司知识库")

    try:
        await client.delete_kb(mapping.weknora_kb_id, trace_id=trace_id)
    except WeKnoraError as exc:
        await session.rollback()
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.config_company_kb_deleted.value,
            trace_id=trace_id,
            target_type="company_knowledge_base",
            extra={"result": "unavailable"},
        )
        await session.commit()
        raise _denied(503, "company_kb_unavailable", "知识库底座暂不可用，请稍后重试") from exc

    await session.delete(mapping)
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.config_company_kb_deleted.value,
        trace_id=trace_id,
        target_type="company_knowledge_base",
        extra={"result": "deleted"},
    )
    await session.commit()
