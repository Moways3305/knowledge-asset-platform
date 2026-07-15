"""公司层与项目层治理授权的唯一纯策略模块。

角色存储仍分别来自 ``user_company_roles`` 与 ``project_members``。本模块只接收可信
``CallerContext`` / 已从数据库读取的角色集合，不接受客户端声明的角色。
"""

from __future__ import annotations

import uuid
from collections.abc import Set

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

# 默认候选策略位于服务层而非数据模型/DB constraint，后续可由配置或策略表替换。
DEFAULT_COACH_COMPANY_ROLES = GOVERNANCE_COMPANY_ROLES


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
    """公司业务角色层级；技术 admin 角色仍由 admin 自身的系统治理入口管理。"""
    if not caller.is_active:
        return False
    roles = caller.active_company_roles
    if target_role == CompanyRole.admin.value:
        return CompanyRole.admin.value in roles
    if CompanyRole.boss.value in roles:
        return target_role in BUSINESS_COMPANY_ROLES
    if CompanyRole.consulting_director.value in roles:
        return target_role in {
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
    """治理角色任命项目经理；项目经理独立管理辅导老师与项目顾问。"""
    if is_governance(caller):
        return requested_role in {
            ProjectRole.project_manager.value,
            ProjectRole.coach.value,
        }
    if not is_project_manager(caller, project_id):
        return False
    return (
        requested_role in PROJECT_MANAGER_MANAGED_ROLES
        and current_role != ProjectRole.project_manager.value
    )


def coach_candidate_allowed(
    company_roles: Set[str],
    *,
    allowed_company_roles: Set[str] = DEFAULT_COACH_COMPANY_ROLES,
) -> bool:
    """默认辅导老师候选策略，可注入其它允许集合扩展，未固化为 DB 约束。"""
    return bool(company_roles & allowed_company_roles)
