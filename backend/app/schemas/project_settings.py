"""项目设置 / 项目成员管理 API 的请求 / 响应 schema。

只暴露**安全治理元数据**。`wecom_group_id` 是配置值，响应**绝不**回全文——只回
`wecom_group_bound: bool` + `wecom_group_label`（脱敏后缀）；PATCH 可接收全文并只存 DB。

绝不返回：wecom_user_id 明文 / token / OAuth code·state / access_token / 微盘 file_id·下载 URL /
内部存储引用 / WeKnora id / provider 内部标识 / 业务原文。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.enums import MemberStatus, ProjectRole


class ProjectSettingsOut(BaseModel):
    """项目设置安全视图。"""

    project_id: uuid.UUID
    name: str
    status: str
    client_name: str | None = None
    # 辅导老师姓名（由 active project_members.project_role=coach 推导，可能多名取首个/拼接）。
    coach_name: str | None = None
    lifecycle_route_key: str | None = None
    lifecycle_phase_key: str | None = None
    force_review_on_ingest: bool = False
    # 企微群：只回是否已绑定 + 脱敏 label，绝不回全文。
    wecom_group_bound: bool = False
    wecom_group_label: str | None = None
    updated_at: datetime
    # 调用人是否对本项目有设置写权限（供前端区分只读 / 可编辑；后端 PATCH 仍兜底校验）。
    can_write: bool = False


class ProjectSettingsUpdateRequest(BaseModel):
    """更新项目设置（至少一项）。wecom_group_id 接收全文、只存 DB；空串视为解绑。"""

    lifecycle_route_key: str | None = None
    lifecycle_phase_key: str | None = None
    force_review_on_ingest: bool | None = None
    wecom_group_id: str | None = None


class ProjectMemberOut(BaseModel):
    """项目成员安全视图。"""

    member_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    email: str
    # active 公司角色 key（安全显示，如 boss/consultant）。
    company_roles: list[str] = []
    project_role: str
    status: str
    # 成员来源：当前未建模成员来源列，统一为 manual（经 /admin/people 维护）；不伪造企微同步来源。
    source: str = "manual"
    joined_at: datetime
    wecom_bound: bool = False


class ProjectMembersResponse(BaseModel):
    items: list[ProjectMemberOut]
    total: int
    # 调用人是否可修改本项目成员（供前端区分只读 / 可编辑）。
    can_manage: bool = False


class ProjectMemberPatchRequest(BaseModel):
    """更新项目成员角色 / 状态（至少一项）。"""

    project_role: ProjectRole | None = None
    status: MemberStatus | None = None


class ProjectMemberCreateRequest(BaseModel):
    """新增或恢复项目成员；项目 ID 只取可信路由参数。"""

    user_id: uuid.UUID
    project_role: ProjectRole
    status: MemberStatus = MemberStatus.active


# ----- 项目列表 / 创建 -----
class ProjectListItemOut(BaseModel):
    """项目列表条目（安全治理元数据）。"""

    id: uuid.UUID
    name: str
    client_name: str | None = None
    status: str
    lifecycle_route_key: str | None = None
    lifecycle_phase_key: str | None = None
    created_at: datetime
    # 调用人是否可管理该项目（治理角色 或 本项目 project_manager）。
    can_manage: bool = False


class ProjectListResponse(BaseModel):
    items: list[ProjectListItemOut]


class ProjectCreateRequest(BaseModel):
    """创建项目知识空间。必须指定 active business user 作为 project_manager。"""

    name: str
    client_name: str | None = None
    project_manager_user_id: uuid.UUID
    coach_user_id: uuid.UUID | None = None
    lifecycle_route_key: str | None = None
    lifecycle_phase_key: str | None = None


class ProjectCreateResponse(BaseModel):
    """创建结果（安全字段）。绝不含 WeKnora id / 企微群全文 / token / URL。"""

    id: uuid.UUID
    name: str
    client_name: str | None = None
    status: str
    lifecycle_route_key: str | None = None
    lifecycle_phase_key: str | None = None
    project_manager_user_id: uuid.UUID
    coach_user_id: uuid.UUID | None = None
    created_at: datetime
