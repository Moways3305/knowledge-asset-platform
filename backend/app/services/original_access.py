"""原文访问申请与授权服务（PBC-06）。

闭环：可发现但无原文权的业务用户发起申请 → 项目 PM/coach 或治理角色审批 → 生成
active access_grant（可过期、可撤销）→ 运行时 `decide()` 原文层统一读取 active grant 放行。

运行时读取入口（`has_active_grant` / `active_grant_asset_ids`）为**纯读 + 时间过滤**
（不变更状态），保证在只读请求上下文也安全；惰性 expired 落库只在写动作 / 列表中进行。

安全：响应 / 审计只含安全枚举 / UUID / 时间 / 安全显示名 / status；绝不含原文 /
storage_ref / source_file_ref / URL / token / WeKnora id / provider 内部标识。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Project, User
from app.models.knowledge import KnowledgeAsset
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.models.permission_rule import PermissionRule
from app.schemas.enums import (
    AccessGrantStatus,
    AccessGrantType,
    AccessRequestStatus,
    AuditAction,
    AuditLogType,
    CompanyRole,
    MemberStatus,
    ProjectRole,
)
from app.schemas.original_access import (
    AccessGrantOut,
    CreateRequestResponse,
    OriginalAccessRequestOut,
    RequestsListResponse,
)
from app.schemas.permission import AccessChannel, AccessLayer, CallerContext
from app.services import audit as audit_service
from app.services.permission import decide

_MANAGEMENT_ROLES = {ProjectRole.project_manager.value, ProjectRole.coach.value}
_DEFAULT_GRANT_DAYS = 7


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"denied_reason": reason, "message": message})


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _is_admin(caller: CallerContext) -> bool:
    return CompanyRole.admin.value in caller.active_company_roles


def _is_governance(caller: CallerContext) -> bool:
    return caller.can_discover_l5  # boss / consulting_director


# ---------------------------------------------------------------------------
# 运行时读取（纯读 + 时间过滤；供 decide() 原文层联动）
# ---------------------------------------------------------------------------
def _grant_is_live(g: AccessGrant) -> bool:
    if g.status != AccessGrantStatus.active.value:
        return False
    exp = _as_aware(g.expires_at)
    return exp is None or exp > _now()


async def has_active_grant(
    session: AsyncSession, user_id: uuid.UUID, asset_id: uuid.UUID
) -> bool:
    """调用人对该资产是否有 active（未过期、未撤销）original_access 授权。纯读。"""
    rows = (
        await session.execute(
            select(AccessGrant).where(
                AccessGrant.grantee_user_id == user_id,
                AccessGrant.asset_id == asset_id,
                AccessGrant.grant_type == AccessGrantType.original_access.value,
                AccessGrant.status == AccessGrantStatus.active.value,
            )
        )
    ).scalars().all()
    return any(_grant_is_live(g) for g in rows)


async def active_grant_asset_ids(
    session: AsyncSession, caller: CallerContext, asset_ids: Iterable[uuid.UUID]
) -> set[uuid.UUID]:
    """批量：调用人在给定资产集合中有 active original_access 授权的子集。纯读。"""
    ids = list({a for a in asset_ids})
    if not ids:
        return set()
    rows = (
        await session.execute(
            select(AccessGrant).where(
                AccessGrant.grantee_user_id == caller.user_id,
                AccessGrant.asset_id.in_(ids),
                AccessGrant.grant_type == AccessGrantType.original_access.value,
                AccessGrant.status == AccessGrantStatus.active.value,
            )
        )
    ).scalars().all()
    return {g.asset_id for g in rows if _grant_is_live(g)}


async def detail_access_state(
    session: AsyncSession, caller: CallerContext, asset_id: uuid.UUID
) -> tuple[bool, datetime | None, bool]:
    """知识详情用：返回 (有 active 原文授权, 授权过期时间, 是否有本人 pending 申请)。纯读。"""
    grants = (
        await session.execute(
            select(AccessGrant).where(
                AccessGrant.grantee_user_id == caller.user_id,
                AccessGrant.asset_id == asset_id,
                AccessGrant.grant_type == AccessGrantType.original_access.value,
                AccessGrant.status == AccessGrantStatus.active.value,
            )
        )
    ).scalars().all()
    live = next((g for g in grants if _grant_is_live(g)), None)
    pending = (
        await session.execute(
            select(OriginalAccessRequest.id).where(
                OriginalAccessRequest.requester_user_id == caller.user_id,
                OriginalAccessRequest.asset_id == asset_id,
                OriginalAccessRequest.status == AccessRequestStatus.pending.value,
            )
        )
    ).scalars().first()
    return (live is not None, _as_aware(live.expires_at) if live else None, pending is not None)


async def _grant_duration_days(session: AsyncSession) -> int:
    """默认授权有效期天数，来自 permission_rules.access_grant_duration_days（缺失回退 7）。"""
    val = (
        await session.execute(
            select(PermissionRule.value_number).where(
                PermissionRule.rule_key == "access_grant_duration_days"
            )
        )
    ).scalars().first()
    try:
        days = int(val) if val is not None else _DEFAULT_GRANT_DAYS
    except (TypeError, ValueError):
        days = _DEFAULT_GRANT_DAYS
    return days if days > 0 else _DEFAULT_GRANT_DAYS


# ---------------------------------------------------------------------------
# 授权 / 审批权限
# ---------------------------------------------------------------------------
def _can_approve(caller: CallerContext, asset: KnowledgeAsset) -> bool:
    """审批 / 撤销权：治理角色，或资产所属项目的 active project_manager / coach。"""
    if _is_governance(caller):
        return True
    if asset.project_id is not None:
        return caller.active_project_roles.get(asset.project_id) in _MANAGEMENT_ROLES
    return False


def _require_approver(caller: CallerContext, asset: KnowledgeAsset) -> None:
    if _can_approve(caller, asset):
        return
    # 纯 admin 系统身份不获业务审批权。
    if _is_admin(caller) and not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "admin 不可审批业务原文授权")
    raise _denied(403, "original_access_review_forbidden", "无原文授权审批 / 撤销权")


# ---------------------------------------------------------------------------
# 安全视图
# ---------------------------------------------------------------------------
async def _name_map(session: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    rows = (await session.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


async def _request_out(
    session: AsyncSession, req: OriginalAccessRequest, *, asset: KnowledgeAsset | None = None
) -> OriginalAccessRequestOut:
    if asset is None:
        asset = (
            await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == req.asset_id))
        ).scalar_one_or_none()
    names = await _name_map(session, {req.requester_user_id, req.reviewer_user_id or uuid.uuid4()})
    return OriginalAccessRequestOut(
        request_id=req.id,
        asset_id=req.asset_id,
        asset_title=asset.title if asset else None,
        scope=asset.scope if asset else None,
        project_id=req.project_id,
        requester_user_id=req.requester_user_id,
        requester_name=names.get(req.requester_user_id),
        reviewer_user_id=req.reviewer_user_id,
        reviewer_name=names.get(req.reviewer_user_id) if req.reviewer_user_id else None,
        requested_access_layer=req.requested_access_layer,
        status=req.status,
        reason=req.reason,
        review_note=req.review_note,
        created_at=req.created_at,
        reviewed_at=req.reviewed_at,
    )


def _grant_out(grant: AccessGrant) -> AccessGrantOut:
    return AccessGrantOut(
        grant_id=grant.id,
        asset_id=grant.asset_id,
        grantee_user_id=grant.grantee_user_id,
        grant_type=grant.grant_type,
        source_request_id=grant.source_request_id,
        status=grant.status,
        expires_at=grant.expires_at,
        created_at=grant.created_at,
        revoked_at=grant.revoked_at,
    )


# ---------------------------------------------------------------------------
# 申请
# ---------------------------------------------------------------------------
async def create_request(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    reason: str | None,
    trace_id: str,
) -> CreateRequestResponse:
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可发起原文访问申请")

    asset = (
        await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))
    ).scalar_one_or_none()
    not_found = _denied(404, "knowledge_asset_not_found", "知识资产不存在或不可见")
    if asset is None:
        raise not_found
    # 至少要能发现该资产，否则不泄露存在。
    if not decide(caller, asset, AccessLayer.discovery).allowed:
        raise not_found

    # 已有原文权（成员 / L1-L2 默认 / 已有 grant）→ 不重复建 pending。
    granted = await has_active_grant(session, caller.user_id, asset.id)
    if decide(caller, asset, AccessLayer.original, has_original_grant=granted).allowed:
        return CreateRequestResponse(
            status="already_granted", request=None,
            message="你已拥有该资产的原文访问权，无需申请",
        )

    existing = (
        await session.execute(
            select(OriginalAccessRequest).where(
                OriginalAccessRequest.requester_user_id == caller.user_id,
                OriginalAccessRequest.asset_id == asset.id,
                OriginalAccessRequest.status == AccessRequestStatus.pending.value,
            )
        )
    ).scalars().first()
    if existing is not None:
        return CreateRequestResponse(
            status="pending_exists", request=await _request_out(session, existing, asset=asset),
            message="已有待审批的原文访问申请",
        )

    req = OriginalAccessRequest(
        asset_id=asset.id,
        requester_user_id=caller.user_id,
        project_id=asset.project_id,
        requested_access_layer=AccessLayer.original.value,
        reason=audit_service.sanitize_text(reason),
        status=AccessRequestStatus.pending.value,
    )
    session.add(req)
    await session.flush()
    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.access_original_requested.value, trace_id=trace_id,
        target_type="original_access_request", target_id=req.id,
        after={"status": req.status},
        extra={"asset_id": str(asset.id), "requester_user_id": str(caller.user_id)},
        project_id=asset.project_id,
    )
    await session.commit()
    return CreateRequestResponse(
        status="created", request=await _request_out(session, req, asset=asset),
        message="原文访问申请已提交，待审批",
    )


# ---------------------------------------------------------------------------
# 列表
# ---------------------------------------------------------------------------
async def list_requests(
    session: AsyncSession, caller: CallerContext, *, box: str = "mine", status: str | None = None
) -> RequestsListResponse:
    """box=mine：本人申请；box=inbox：可审批的 pending 申请（治理角色全部，PM/coach 限本项目）。"""
    if not caller.is_business_user:
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可查看原文访问申请")

    stmt = select(OriginalAccessRequest)
    if box == "mine":
        stmt = stmt.where(OriginalAccessRequest.requester_user_id == caller.user_id)
        if status:
            stmt = stmt.where(OriginalAccessRequest.status == status)
        rows = list((await session.execute(stmt.order_by(OriginalAccessRequest.created_at.desc()))).scalars().all())
    else:  # inbox：只看 pending
        stmt = stmt.where(OriginalAccessRequest.status == AccessRequestStatus.pending.value)
        rows = list((await session.execute(stmt.order_by(OriginalAccessRequest.created_at.desc()))).scalars().all())

    asset_ids = {r.asset_id for r in rows}
    assets: dict[uuid.UUID, KnowledgeAsset] = {}
    if asset_ids:
        for a in (await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id.in_(asset_ids)))).scalars().all():
            assets[a.id] = a

    if box != "mine":
        # inbox：仅保留调用人可审批的资产对应申请。
        rows = [r for r in rows if (assets.get(r.asset_id) is not None and _can_approve(caller, assets[r.asset_id]))]

    items = [await _request_out(session, r, asset=assets.get(r.asset_id)) for r in rows]
    return RequestsListResponse(items=items, total=len(items))


# ---------------------------------------------------------------------------
# 审批 / 拒绝
# ---------------------------------------------------------------------------
async def _load_request(session: AsyncSession, request_id: uuid.UUID) -> tuple[OriginalAccessRequest, KnowledgeAsset]:
    req = (
        await session.execute(select(OriginalAccessRequest).where(OriginalAccessRequest.id == request_id))
    ).scalar_one_or_none()
    if req is None:
        raise _denied(404, "original_access_request_not_found", "原文访问申请不存在")
    asset = (
        await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == req.asset_id))
    ).scalar_one_or_none()
    if asset is None:
        raise _denied(404, "knowledge_asset_not_found", "资产不存在")
    return req, asset


async def approve_request(
    session: AsyncSession, caller: CallerContext, request_id: uuid.UUID, note: str | None, trace_id: str
) -> CreateRequestResponse:
    req, asset = await _load_request(session, request_id)
    _require_approver(caller, asset)
    if req.status != AccessRequestStatus.pending.value:
        raise _denied(409, "request_already_finalized", "申请已处理，不能重复审批")

    req.status = AccessRequestStatus.approved.value
    req.reviewer_user_id = caller.user_id
    req.reviewed_at = _now()
    req.review_note = audit_service.sanitize_text(note)

    # 复用 / 新建 active grant（同 grantee+asset+type 至多一个 active）。
    existing_grant = (
        await session.execute(
            select(AccessGrant).where(
                AccessGrant.grantee_user_id == req.requester_user_id,
                AccessGrant.asset_id == asset.id,
                AccessGrant.grant_type == AccessGrantType.original_access.value,
                AccessGrant.status == AccessGrantStatus.active.value,
            )
        )
    ).scalars().first()
    days = await _grant_duration_days(session)
    if existing_grant is not None and _grant_is_live(existing_grant):
        grant = existing_grant
    else:
        grant = AccessGrant(
            asset_id=asset.id,
            grantee_user_id=req.requester_user_id,
            grant_type=AccessGrantType.original_access.value,
            source_request_id=req.id,
            granted_by_user_id=caller.user_id,
            status=AccessGrantStatus.active.value,
            expires_at=_now() + timedelta(days=days),
        )
        session.add(grant)
    await session.flush()

    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.access_original_approved.value, trace_id=trace_id,
        target_type="access_grant", target_id=grant.id,
        before={"request_status": AccessRequestStatus.pending.value},
        after={"request_status": req.status, "grant_status": grant.status, "expires_at": grant.expires_at.isoformat() if grant.expires_at else None},
        extra={"asset_id": str(asset.id), "grantee_user_id": str(req.requester_user_id), "source_request_id": str(req.id)},
        project_id=asset.project_id,
    )
    await session.commit()
    return CreateRequestResponse(
        status="approved", request=await _request_out(session, req, asset=asset),
        grant=_grant_out(grant), message="已审批通过并生成原文访问授权",
    )


async def reject_request(
    session: AsyncSession, caller: CallerContext, request_id: uuid.UUID, note: str | None, trace_id: str
) -> CreateRequestResponse:
    req, asset = await _load_request(session, request_id)
    _require_approver(caller, asset)
    if req.status != AccessRequestStatus.pending.value:
        raise _denied(409, "request_already_finalized", "申请已处理，不能重复审批")

    req.status = AccessRequestStatus.rejected.value
    req.reviewer_user_id = caller.user_id
    req.reviewed_at = _now()
    req.review_note = audit_service.sanitize_text(note)
    await session.flush()
    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.access_original_rejected.value, trace_id=trace_id,
        target_type="original_access_request", target_id=req.id,
        before={"status": AccessRequestStatus.pending.value}, after={"status": req.status},
        extra={"asset_id": str(asset.id), "requester_user_id": str(req.requester_user_id)},
        project_id=asset.project_id,
    )
    await session.commit()
    return CreateRequestResponse(
        status="rejected", request=await _request_out(session, req, asset=asset), message="已拒绝原文访问申请",
    )


# ---------------------------------------------------------------------------
# 撤销授权
# ---------------------------------------------------------------------------
async def revoke_grant(
    session: AsyncSession, caller: CallerContext, grant_id: uuid.UUID, reason: str | None, trace_id: str
) -> AccessGrantOut:
    grant = (
        await session.execute(select(AccessGrant).where(AccessGrant.id == grant_id))
    ).scalar_one_or_none()
    if grant is None:
        raise _denied(404, "access_grant_not_found", "授权不存在")
    asset = (
        await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == grant.asset_id))
    ).scalar_one_or_none()
    if asset is None:
        raise _denied(404, "knowledge_asset_not_found", "资产不存在")

    # 授权人 / 项目 PM·coach / 治理角色可撤销；被授权人可放弃自己的授权（单独审计）。
    self_revoke = grant.grantee_user_id == caller.user_id and caller.is_business_user
    if not (self_revoke or _can_approve(caller, asset) or grant.granted_by_user_id == caller.user_id):
        if _is_admin(caller) and not caller.is_business_user:
            raise _denied(403, "admin_business_permission_denied", "admin 不可撤销业务原文授权")
        raise _denied(403, "original_access_revoke_forbidden", "无原文授权撤销权")

    if grant.status != AccessGrantStatus.active.value:
        raise _denied(409, "grant_not_active", "授权非 active，无需撤销")

    grant.status = AccessGrantStatus.revoked.value
    grant.revoked_at = _now()
    grant.revoked_by_user_id = caller.user_id
    grant.revoke_reason = audit_service.sanitize_text(reason)
    await session.flush()
    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.access_original_grant_revoked.value, trace_id=trace_id,
        target_type="access_grant", target_id=grant.id,
        before={"status": AccessGrantStatus.active.value}, after={"status": grant.status},
        extra={
            "asset_id": str(asset.id), "grantee_user_id": str(grant.grantee_user_id),
            "self_revoke": self_revoke,
        },
        project_id=asset.project_id,
    )
    await session.commit()
    return _grant_out(grant)
