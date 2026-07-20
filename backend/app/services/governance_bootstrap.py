"""首位总经理的一次性、非 HTTP 初始化服务。"""

from __future__ import annotations

import uuid
from enum import Enum

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import User, UserCompanyRole
from app.schemas.enums import AuditAction, AuditLogType, CompanyRole, RoleStatus, UserStatus
from app.services import audit as audit_service

_POSTGRES_LOCK_KEY = 726_060


class BossBootstrapResult(str, Enum):
    created = "boss_bootstrap_created"
    already_configured = "boss_bootstrap_already_configured"
    target_unavailable = "boss_bootstrap_target_unavailable"


async def _lock_bootstrap(session: AsyncSession) -> None:
    """PostgreSQL 事务级互斥；测试 SQLite 由单连接事务提供串行语义。"""
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": _POSTGRES_LOCK_KEY}
        )


async def bootstrap_first_boss(
    session: AsyncSession, *, target_user_id: uuid.UUID, trace_id: str
) -> BossBootstrapResult:
    """仅在没有可用总经理时，把一个已存在的 active 用户设为总经理。"""
    await _lock_bootstrap(session)
    active_boss = (
        await session.execute(
            select(UserCompanyRole.id)
            .join(User, User.id == UserCompanyRole.user_id)
            .where(
                UserCompanyRole.company_role == CompanyRole.boss.value,
                UserCompanyRole.status == RoleStatus.active.value,
                User.status == UserStatus.active.value,
            )
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if active_boss is not None:
        await session.rollback()
        return BossBootstrapResult.already_configured

    target = (
        await session.execute(
            select(User)
            .where(User.id == target_user_id, User.status == UserStatus.active.value)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if target is None:
        await session.rollback()
        return BossBootstrapResult.target_unavailable

    role = (
        await session.execute(
            select(UserCompanyRole).where(
                UserCompanyRole.user_id == target.id,
                UserCompanyRole.company_role == CompanyRole.boss.value,
            )
        )
    ).scalar_one_or_none()
    if role is None:
        session.add(
            UserCompanyRole(
                user_id=target.id,
                company_role=CompanyRole.boss.value,
                status=RoleStatus.active.value,
            )
        )
    else:
        role.status = RoleStatus.active.value
    await session.flush()
    await audit_service.record_system_event(
        session,
        log_type=AuditLogType.operation,
        action=AuditAction.governance_boss_bootstrapped.value,
        trace_id=trace_id,
        target_type="company_governance",
        extra={"result": "created"},
    )
    await session.commit()
    return BossBootstrapResult.created
