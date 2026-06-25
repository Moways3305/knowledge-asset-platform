"""个人知识库管理服务（PBC-29）。

业务用户对**自己**的个人知识库做：显式创建（幂等 / init_failed 重试）、查看状态、改名
（同步底座，底座失败降级不回滚平台侧）。

owner-only：每个动作都要求 caller 是 active 业务用户，且只操作 `scope=personal` +
`owner_user_id == caller.user_id` 的映射；纯 admin（非业务用户）一律 403——admin 走
`/admin/weknora/*`，个人库不是 admin 的旁路。

安全：响应 / 审计只含安全元数据（可读名 / 状态 / 计数 / index 分布 / 安全 model_ref /
sync_ok 布尔）。绝不暴露 WeKnora 内部库标识 / raw 模型 id / api_key / 底座存储·分块配置。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import AssetStatus, AuditAction, AuditLogType, KnowledgeScope
from app.schemas.permission import CallerContext
from app.schemas.personal_kb import PersonalKbOut
from app.services import audit as audit_service
from app.services import weknora_models
from app.services.weknora_client import (
    NullWeKnoraClient,
    WeKnoraClient,
    WeKnoraError,
)
from app.services.weknora_kb import (
    DEFAULT_PERSONAL_KB_NAME,
    resolve_or_create_kb,
)
from app.services.weknora_model_selection import resolve_models_for_kb

_STATUS_ACTIVE = "active"
_CheckClient = "WeKnoraClient | NullWeKnoraClient"


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _require_business_user(caller: CallerContext) -> None:
    """owner-only 前置闸：仅 active 业务用户。纯 admin / inactive → 403。"""
    if not caller.is_active or not caller.is_business_user:
        raise _denied(403, "personal_kb_forbidden", "仅业务用户可管理个人知识库")


def _safe_model_ref(model_id: str | None) -> str | None:
    """raw embedding model id → 对前端不可逆的安全 model_ref（PBC-11A 映射）。空 → None。"""
    mid = (model_id or "").strip()
    if not mid or mid == "None":
        return None
    return weknora_models._model_ref(mid)


async def _find_personal_mapping(
    session: AsyncSession, owner_user_id: uuid.UUID
) -> WeknoraKbMapping | None:
    return (
        await session.execute(
            select(WeknoraKbMapping)
            .where(WeknoraKbMapping.scope == KnowledgeScope.personal.value)
            .where(WeknoraKbMapping.owner_user_id == owner_user_id)
        )
    ).scalar_one_or_none()


async def _status_out(
    session: AsyncSession,
    mapping: WeknoraKbMapping,
    owner_user_id: uuid.UUID,
    *,
    weknora_sync_failed: bool = False,
) -> PersonalKbOut:
    """组装安全状态视图：资产计数 + active 版本 index 分布 + 安全 embedding ref。"""
    active_personal = (
        KnowledgeAsset.scope == KnowledgeScope.personal.value,
        KnowledgeAsset.owner_user_id == owner_user_id,
        KnowledgeAsset.asset_status != AssetStatus.deleted.value,
    )
    knowledge_count = int(
        (
            await session.execute(
                select(func.count()).select_from(KnowledgeAsset).where(*active_personal)
            )
        ).scalar()
        or 0
    )
    dist_rows = (
        await session.execute(
            select(KnowledgeAssetVersion.index_status, func.count())
            .select_from(KnowledgeAssetVersion)
            .join(KnowledgeAsset, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            .where(*active_personal, KnowledgeAssetVersion.version_status == "active")
            .group_by(KnowledgeAssetVersion.index_status)
        )
    ).all()
    index_distribution = {str(status): int(n) for status, n in dist_rows}
    return PersonalKbOut(
        exists=True,
        display_name=mapping.display_name or DEFAULT_PERSONAL_KB_NAME,
        status=mapping.status,
        knowledge_count=knowledge_count,
        index_distribution=index_distribution,
        embedding_model_ref=_safe_model_ref(mapping.embedding_model_id),
        created_at=mapping.created_at,
        weknora_sync_failed=weknora_sync_failed,
    )


async def get_personal_kb(
    session: AsyncSession, caller: CallerContext, *, trace_id: str | None = None
) -> PersonalKbOut:
    """查看个人 KB 状态。无映射 → exists=False。纯 DB 查询，未配置底座也能安全返回。"""
    _require_business_user(caller)
    mapping = await _find_personal_mapping(session, caller.user_id)
    if mapping is None:
        return PersonalKbOut(exists=False)
    return await _status_out(session, mapping, caller.user_id)


async def create_personal_kb(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    caller: CallerContext,
    *,
    display_name: str | None,
    embedding_model_ref: str | None = None,
    rerank_model_ref: str | None = None,
    trace_id: str | None = None,
) -> PersonalKbOut:
    """显式创建个人 KB。幂等：已 active → 返回现有（不重复建、不改名）；init_failed → 重试初始化。

    PBC-38：可选 embedding_model_ref / rerank_model_ref（model_ref，缺省走平台默认）。
    未配置底座 / 缺 embedding 模型 / 平台默认未配置 → fail-closed 安全 503（不写映射、不假成功）。
    """
    _require_business_user(caller)
    name = (display_name or "").strip() or DEFAULT_PERSONAL_KB_NAME

    existing = await _find_personal_mapping(session, caller.user_id)
    if existing is not None and existing.status == _STATUS_ACTIVE:
        return await _status_out(session, existing, caller.user_id)

    if isinstance(client, NullWeKnoraClient):
        # 未配置底座：无法建库（映射要求 weknora_kb_id 非空），fail-closed 安全提示。
        raise _denied(503, "personal_kb_unavailable", "知识库底座未配置，暂无法创建个人知识库")

    try:
        models = await resolve_models_for_kb(
            session,
            client,
            embedding_model_ref=embedding_model_ref,
            rerank_model_ref=rerank_model_ref,
            trace_id=trace_id,
        )
        await resolve_or_create_kb(
            session,
            client,
            scope=KnowledgeScope.personal.value,
            owner_user_id=caller.user_id,
            project_id=None,
            models=models,
            trace_id=trace_id,
            display_name=name,
        )
    except WeKnoraError as exc:
        # resolve 内部已独立提交映射（成功 active / 初始化失败 init_failed）后才抛。
        await session.rollback()
        mapping = await _find_personal_mapping(session, caller.user_id)
        if mapping is None:
            # 连库都没建起来（如缺 embedding 模型）→ fail-closed，不留半成品。
            raise _denied(
                503, "personal_kb_unavailable", "知识库底座暂不可用，请稍后重试或联系管理员"
            ) from exc
        # 映射已落 init_failed：记录创建审计并返回状态（前端可引导重试）。
        await _audit(
            session,
            caller,
            mapping,
            AuditAction.config_personal_kb_created.value,
            trace_id,
            sync_ok=False,
            name_before=None,
            name_after=mapping.display_name,
        )
        await session.commit()
        return await _status_out(session, mapping, caller.user_id)

    mapping = await _find_personal_mapping(session, caller.user_id)
    # 紧接上面的创建路径，映射必已存在。
    assert mapping is not None
    await _audit(
        session,
        caller,
        mapping,
        AuditAction.config_personal_kb_created.value,
        trace_id,
        sync_ok=True,
        name_before=None,
        name_after=mapping.display_name,
    )
    await session.commit()
    return await _status_out(session, mapping, caller.user_id)


async def rename_personal_kb(
    session: AsyncSession,
    client: WeKnoraClient | NullWeKnoraClient,
    caller: CallerContext,
    *,
    display_name: str,
    trace_id: str | None = None,
) -> PersonalKbOut:
    """改名：更新平台 display_name + 同步底座 name。

    底座同步失败**不回滚平台侧**（可读名是平台展示层关注；底座 slug 不影响索引功能），
    返回 `weknora_sync_failed=True` 让前端提示「名称已保存，底座同步稍后重试」。
    """
    _require_business_user(caller)
    mapping = await _find_personal_mapping(session, caller.user_id)
    if mapping is None:
        raise _denied(404, "personal_kb_not_found", "你还没有个人知识库")

    name = audit_service.sanitize_text(display_name.strip()) or DEFAULT_PERSONAL_KB_NAME
    name_before = mapping.display_name
    mapping.display_name = name

    sync_ok = True
    try:
        await client.update_kb(mapping.weknora_kb_id, name=name, trace_id=trace_id)
    except WeKnoraError:
        # 底座同步失败（含未配置）：平台侧已改名、不回滚，标记待重试。
        sync_ok = False

    await _audit(
        session,
        caller,
        mapping,
        AuditAction.config_personal_kb_updated.value,
        trace_id,
        sync_ok=sync_ok,
        name_before=name_before,
        name_after=name,
    )
    await session.commit()
    return await _status_out(session, mapping, caller.user_id, weknora_sync_failed=not sync_ok)


async def _audit(
    session: AsyncSession,
    caller: CallerContext,
    mapping: WeknoraKbMapping,
    action: str,
    trace_id: str | None,
    *,
    sync_ok: bool,
    name_before: str | None,
    name_after: str | None,
) -> None:
    """个人 KB 配置审计：只记安全元数据（前后可读名 + sync_ok），**绝不**含 weknora 库标识。"""
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=action,
        trace_id=trace_id or "",
        target_type="personal_knowledge_base",
        target_id=mapping.id,
        extra={
            "display_name_before": name_before,
            "display_name_after": name_after,
            "weknora_sync_ok": sync_ok,
        },
    )
