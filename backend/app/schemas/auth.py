"""`/api/v1/auth/me` 响应 schema。

字段名严格对齐 BE-04 第 5 章身份上下文契约。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class ProjectMembershipOut(BaseModel):
    """单条项目成员关系（仅 active 会被返回）。"""

    project_id: uuid.UUID
    project_name: str
    project_role: str
    status: str


class LoginRequest(BaseModel):
    """登录请求。提供 password → 所有环境走真实密码校验；
    不提供 password → 仅 local/dev/test 走无凭证开发适配器，prod 拒绝。
    password 仅入站校验、绝不回显。"""

    email: str
    password: str | None = None


class LogoutResponse(BaseModel):
    ok: bool


class CsrfTokenOut(BaseModel):
    """CSRF token 下发响应。

    csrf_token 是签名 + 过期 + 绑定 session 的不透明串（非认证凭证、不含 session token /
    cookie 值）；前端内存缓存并经 `X-CSRF-Token` 头回送 unsafe 请求。
    """

    csrf_token: str
    expires_at: datetime


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

