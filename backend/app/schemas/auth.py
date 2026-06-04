"""`/api/v1/auth/me` 响应 schema。

字段名严格对齐 BE-04 第 5 章身份上下文契约。
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class ProjectMembershipOut(BaseModel):
    """单条项目成员关系（仅 active 会被返回）。"""

    project_id: uuid.UUID
    project_name: str
    project_role: str
    status: str


class LoginRequest(BaseModel):
    """本地登录请求（开发环境无凭证适配器）。真实 OAuth 接入后由授权码流替换。"""

    email: str


class LogoutResponse(BaseModel):
    ok: bool


class WecomAuthorizeOut(BaseModel):
    """企微 OAuth 授权 URL（R6）。state 在 httpOnly cookie 里校验，不进本响应。

    authorize_url 含 corp_id/redirect/state，但**绝不**含 app_secret / access_token。
    """

    authorize_url: str


class AuthMeOut(BaseModel):
    """当前用户身份上下文。

    company_roles 与 project_memberships 分开返回；admin 出现在 company_roles
    中不等于拥有业务权限。is_business_user / can_discover_l5 由 active 公司角色推导。
    """

    user_id: uuid.UUID
    name: str
    email: str
    status: str
    company_roles: list[str]
    is_business_user: bool
    can_discover_l5: bool
    project_memberships: list[ProjectMembershipOut]
