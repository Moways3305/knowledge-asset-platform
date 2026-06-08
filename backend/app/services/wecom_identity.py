"""企微身份生命周期同步服务。

把平台用户生命周期对齐其绑定的企微成员有效性：当绑定的企微成员被禁用 / 删除 / 未激活 /
无效时，**fail-closed**——停用平台用户（active→inactive）并经 撤销其活动平台会话，
写安全审计。供 OAuth 回调（系统触发）与 admin 对账端点（admin 触发）共用。

安全红线：响应 / 审计**绝不**含 raw wecom_user_id / access_token / app_secret / OAuth code·state /
上游 payload·errmsg / 手机·邮箱·部门·头像等通讯录档案 / session token·hash·cookie。本任务**不**
删除用户、**不**改公司角色 / 项目成员关系、**不**自动建用户。
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User
from app.schemas.enums import AuditAction, AuditLogType
from app.schemas.permission import CallerContext
from app.schemas.wecom_identity import ReconcileItem, ReconcileResponse
from app.services import audit as audit_service
from app.services import session_revocation
from app.services.wecom_client import WeComError, WeComMemberStatus

_MAX_LIMIT = 200


def _denied(status: int, reason: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"denied_reason": reason, "message": message})


async def apply_member_status(
    session: AsyncSession,
    user: User,
    member: WeComMemberStatus,
    *,
    trigger: str,
    dry_run: bool,
    actor_caller: CallerContext | None,
    trace_id: str,
) -> ReconcileItem:
    """按企微成员状态对单个平台用户做生命周期处置（只 add/flush，不 commit）。

    member 有效 → 不变更。member 无效 → 停用（若当前 active）+ 撤销活动会话 + 安全审计。
    `dry_run` 只回报「将会发生什么」，不做任何变更 / 审计。actor_caller=None → 系统事件。
    """
    prev = user.status
    if member.active:
        return ReconcileItem(
            user_id=user.id, user_name=user.name, previous_status=prev, new_status=prev,
            wecom_status=member.status_code, sessions_revoked=0,
        )

    intended_status = "inactive" if prev == "active" else prev
    if dry_run:
        return ReconcileItem(
            user_id=user.id, user_name=user.name, previous_status=prev,
            new_status=intended_status, wecom_status=member.status_code, sessions_revoked=0,
        )

    if prev == "active":
        user.status = "inactive"
        await session.flush()
    revoked, _ = await session_revocation.revoke_user_sessions(session, user.id)

    extra = {
        "target_user_id": str(user.id),
        "trigger": trigger,
        "wecom_status": member.status_code,
        "previous_status": prev,
        "new_status": intended_status,
        "sessions_revoked": revoked,
    }
    if actor_caller is not None:
        await audit_service.record_event(
            session, caller=actor_caller, log_type=AuditLogType.operation,
            action=AuditAction.identity_user_deactivated_by_wecom_sync.value, trace_id=trace_id,
            target_type="user", target_id=user.id, extra=extra,
        )
    else:
        await audit_service.record_system_event(
            session, log_type=AuditLogType.login,
            action=AuditAction.identity_user_deactivated_by_wecom_sync.value, trace_id=trace_id,
            target_type="user", target_id=user.id, extra=extra,
        )
    return ReconcileItem(
        user_id=user.id, user_name=user.name, previous_status=prev, new_status=intended_status,
        wecom_status=member.status_code, sessions_revoked=revoked,
    )


async def reconcile(
    session: AsyncSession,
    caller: CallerContext,
    oauth,
    *,
    user_id: uuid.UUID | None,
    limit: int,
    dry_run: bool,
    trace_id: str,
) -> ReconcileResponse:
    """对账绑定企微的平台用户（admin-only，权限由调用方校验）。"""
    if user_id is not None:
        user = (await session.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
        if user is None:
            raise _denied(404, "user_not_found", "用户不存在")
        if not user.wecom_user_id:
            raise _denied(422, "user_not_wecom_bound", "该用户未绑定企微")
        users = [user]
    else:
        lim = max(1, min(int(limit), _MAX_LIMIT))
        users = list(
            (
                await session.execute(
                    select(User).where(User.wecom_user_id.is_not(None))
                    .order_by(User.created_at).limit(lim)
                )
            ).scalars().all()
        )

    items: list[ReconcileItem] = []
    for u in users:
        try:
            member = await oauth.get_member_status(u.wecom_user_id)
        except WeComError as exc:
            # 上游 / 未配置失败 → 该用户对账失败，**不**改平台状态（仅安全 code，不回显 errmsg）。
            items.append(ReconcileItem(
                user_id=u.id, user_name=u.name, previous_status=u.status, new_status=u.status,
                wecom_status="unknown", sessions_revoked=0, error_code=exc.code,
            ))
            continue
        items.append(await apply_member_status(
            session, u, member, trigger="admin_reconcile", dry_run=dry_run,
            actor_caller=caller, trace_id=trace_id,
        ))

    checked = len(items)
    deactivated = sum(
        1 for it in items
        if it.error_code is None and it.previous_status == "active" and it.new_status == "inactive"
    )
    already_inactive = sum(1 for it in items if it.error_code is None and it.previous_status != "active")
    failed = sum(1 for it in items if it.error_code is not None)

    # 批量摘要审计（安全计数；单条停用已各自审计）。dry_run 不写停用审计但记录摘要。
    await audit_service.record_event(
        session, caller=caller, log_type=AuditLogType.operation,
        action=AuditAction.identity_wecom_user_synced.value, trace_id=trace_id,
        target_type="user", target_id=(users[0].id if user_id is not None and users else None),
        extra={"trigger": "admin_reconcile", "checked": checked, "deactivated": deactivated,
               "already_inactive": already_inactive, "failed": failed, "dry_run": dry_run},
    )
    await session.commit()
    return ReconcileResponse(
        ok=True, checked=checked, deactivated=deactivated, already_inactive=already_inactive,
        failed=failed, dry_run=dry_run, items=items,
    )

