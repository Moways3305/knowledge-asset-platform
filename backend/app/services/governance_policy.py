"""公司层与项目层治理授权的唯一纯策略模块。

角色存储仍分别来自 ``user_company_roles`` 与 ``project_members``。本模块只接收可信
``CallerContext`` / 已从数据库读取的角色集合，不接受客户端声明的角色。
"""

from __future__ import annotations

import uuid

from app.schemas.enums import CompanyRole, ProjectRole
from app.schemas.permission import CallerContext

GOVERNANCE_COMPANY_ROLES = frozenset(
    {CompanyRole.boss.value, CompanyRole.consulting_director.value}
)
BUSINESS_COMPANY_ROLES = frozenset(
    {
        CompanyRole.boss.value,
        CompanyRole.consulting_director.value,
        CompanyRole.consultant.value,
    }
)
PROJECT_MEMBER_ROLES = frozenset(
    {
        ProjectRole.project_manager.value,
        ProjectRole.coach.value,
        ProjectRole.consultant.value,
    }
)
PROJECT_MANAGER_MANAGED_ROLES = frozenset({ProjectRole.coach.value, ProjectRole.consultant.value})


def is_admin(caller: CallerContext) -> bool:
    return caller.is_active and CompanyRole.admin.value in caller.active_company_roles


def is_governance(caller: CallerContext) -> bool:
    return caller.is_active and bool(caller.active_company_roles & GOVERNANCE_COMPANY_ROLES)


def governance_confirmation_role(caller: CallerContext) -> str | None:
    """返回调用人可代表的单个确认角色；双角色按稳定顺序返回总经理。"""
    if not caller.is_active:
        return None
    if CompanyRole.boss.value in caller.active_company_roles:
        return CompanyRole.boss.value
    if CompanyRole.consulting_director.value in caller.active_company_roles:
        return CompanyRole.consulting_director.value
    return None


def can_manage_company_role(caller: CallerContext, target_role: str) -> bool:
    """公司角色管理层级。总经理可管理 admin / 总经理 / 咨询总监 / 顾问；咨询总监可管理 admin / 咨询总监 / 顾问。"""
    if not caller.is_active:
        return False
    roles = caller.active_company_roles
    if CompanyRole.boss.value in roles:
        return target_role in {
            CompanyRole.admin.value,
            CompanyRole.boss.value,
            CompanyRole.consulting_director.value,
            CompanyRole.consultant.value,
        }
    if CompanyRole.consulting_director.value in roles:
        return target_role in {
            CompanyRole.admin.value,
            CompanyRole.consulting_director.value,
            CompanyRole.consultant.value,
        }
    return False


def project_role(caller: CallerContext, project_id: uuid.UUID) -> str | None:
    return caller.active_project_roles.get(project_id)


def can_access_project(caller: CallerContext, project_id: uuid.UUID) -> bool:
    """公司层角色绝不自动形成项目访问权。"""
    return caller.is_active and project_role(caller, project_id) in PROJECT_MEMBER_ROLES


def is_project_manager(caller: CallerContext, project_id: uuid.UUID) -> bool:
    return (
        caller.is_active and project_role(caller, project_id) == ProjectRole.project_manager.value
    )


def can_assign_project_role(
    caller: CallerContext,
    project_id: uuid.UUID,
    *,
    current_role: str | None,
    requested_role: str,
) -> bool:
    """项目内项目经理可管理辅导老师与顾问；治理角色可任命项目经理。

    当用户在某项目内具有 project_manager 角色时，无论当前 active 公司角色是
    否为治理角色，均优先按该项目经理权限处理，保证项目层面的自治。
    """
    if is_project_manager(caller, project_id):
        if requested_role == ProjectRole.project_manager.value:
            return False
        return (
            requested_role in PROJECT_MANAGER_MANAGED_ROLES
            and current_role != ProjectRole.project_manager.value
        )
    if is_governance(caller):
        return requested_role == ProjectRole.project_manager.value
    return False
