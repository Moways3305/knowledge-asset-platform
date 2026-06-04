"""人员 / 公司角色 / 项目成员关系管理 API 的请求 / 响应 schema（PBC-02）。

只暴露**安全身份/治理元数据**：绝不含 session token / token_hash / OAuth code·state /
ip / device_info / WeCom secret / provider 内部标识 / 内部存储引用 / 业务原文。

`wecom_user_id` 不直接外泄——只暴露 `wecom_bound: bool`（是否已绑定企微）。
`recent_session_at` 由 `user_sessions` 的 last_seen_at / created_at 安全聚合，可为空。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.enums import CompanyRole, MemberStatus, ProjectRole, RoleStatus


class CompanyRoleOut(BaseModel):
    role_id: uuid.UUID
    company_role: str
    status: str


class PersonProjectMembershipOut(BaseModel):
    membership_id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    project_role: str
    status: str
    joined_at: datetime


class PersonOut(BaseModel):
    """人员安全视图。绝不含 wecom_user_id 明文 / token / session / 业务原文。"""

    user_id: uuid.UUID
    name: str
    email: str
    phone: str | None = None
    # 是否已绑定企微（不返回企微内部标识本身）。
    wecom_bound: bool = False
    status: str
    created_at: datetime
    updated_at: datetime
    company_roles: list[CompanyRoleOut] = []
    project_memberships: list[PersonProjectMembershipOut] = []
    # 安全聚合的最近会话时间（last_seen_at / created_at 的最大值），无会话时为 None。
    recent_session_at: datetime | None = None


class PeopleListResponse(BaseModel):
    items: list[PersonOut]
    total: int


class CompanyRoleUpdateRequest(BaseModel):
    """设置 / 启停用户公司角色（upsert）。"""

    company_role: CompanyRole
    status: RoleStatus = RoleStatus.active


class ProjectMembershipCreateRequest(BaseModel):
    """新增 / 恢复项目成员关系（upsert by user_id + project_id）。"""

    project_id: uuid.UUID
    project_role: ProjectRole
    status: MemberStatus = MemberStatus.active


class ProjectMembershipPatchRequest(BaseModel):
    """更新项目成员关系角色 / 状态（至少一项）。"""

    project_role: ProjectRole | None = None
    status: MemberStatus | None = None
