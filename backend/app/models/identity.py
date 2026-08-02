"""身份与项目成员 ORM 模型。

按 `docs/backend/01-数据模型DATA_MODEL.md` 实现最小必需字段：
users / user_company_roles / projects / project_members。

枚举值以 String 存储（跨 PostgreSQL / SQLite 友好），取值约束由应用层
`app.schemas.enums` 保证；类名、字段名、枚举 key 使用英文契约名。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.utils import utc_now


class User(Base):
    """用户：所有操作的发起者。

    公司角色通过 user_company_roles 关联；项目角色通过 project_members 关联。
    本模型不直接持有任何角色，避免把"公司身份"与"项目权限"耦合。
    """

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("wecom_corp_id", "wecom_user_id", name="uq_users_wecom_corp_userid"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # 企微绑定键：corp_id + userid 唯一。userid 为 server-only，API 只暴露 wecom_bound。
    wecom_corp_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    wecom_user_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 企微安全展示/同步字段：不作为登录唯一身份，不进入审计 extra。
    wecom_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    wecom_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wecom_avatar: Mapped[str | None] = mapped_column(String(500), nullable=True)
    wecom_department_ids: Mapped[str | None] = mapped_column(Text, nullable=True)
    wecom_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # status：active / inactive。inactive 用户不应被视为有效业务身份。
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # 密码凭证。password_hash 为 server-only PBKDF2 编码哈希（pbkdf2_sha256$...），
    # **绝不**进任何响应 schema / 审计 / 日志；对外只暴露安全布尔 password_set（=hash 非空）。
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    company_roles: Mapped[list[UserCompanyRole]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    project_members: Mapped[list[ProjectMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class UserCompanyRole(Base):
    """用户公司角色（多对一到 user）。

    - 一个用户可拥有多个公司角色（如同时是 consultant 和 admin）。
    - UNIQUE(user_id, company_role)：同一用户同一公司角色不重复。
    - admin 出现在此表不代表拥有业务治理权限。
    """

    __tablename__ = "user_company_roles"
    __table_args__ = (UniqueConstraint("user_id", "company_role", name="uq_user_company_role"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    # company_role：boss / consulting_director / consultant / admin
    company_role: Mapped[str] = mapped_column(String(30), nullable=False)
    # status：active / inactive。只有 active 角色参与身份判定。
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="company_roles")


class Project(Base):
    """项目：项目基础信息 + 项目设置。

    新增最小必要项目设置字段（生命周期路线 / 阶段、入库强制审核开关、企微群配置）。
    辅导老师（coach）不加列，由 active `project_members.project_role=coach` 推导。
    `wecom_group_id` 是配置值（非 secret），但响应只回脱敏 label + bound，不外泄全文。
    """

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # status：active / completed / archived
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # 客户名称（安全显示字段，可空）。
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # 生命周期路线 key（route_A/B/C），默认 route_A。
    lifecycle_route_key: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="route_A"
    )
    # 当前生命周期阶段标签（可空）。
    lifecycle_phase_key: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 项目入库是否强制进入审核（true 时不允许 direct_ingest）。
    force_review_on_ingest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 企微群配置值（非 secret；响应只回脱敏 label + bound，绝不外泄全文）。
    wecom_group_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Published naming policy projection. Draft edits live in NamingRuleRevision
    # and only reach these columns through an explicit publish transaction.
    project_code: Mapped[str | None] = mapped_column(String(20), nullable=True, unique=True)
    project_code_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    naming_default_confidentiality: Mapped[str] = mapped_column(
        String(2), nullable=False, default="L2"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )

    members: Mapped[list[ProjectMember]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(Base):
    """项目成员关系：项目角色的唯一来源。

    - 项目角色来自本表，不来自 company_roles。
    - UNIQUE(user_id, project_id)：同一用户在同一项目只有一条记录。
    - 只有 status=active 的成员关系才赋予项目知识库访问权（后续权限任务使用）。
    """

    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("user_id", "project_id", name="uq_user_project_member"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("projects.id"), nullable=False)
    # project_role：consultant / project_manager / coach
    project_role: Mapped[str] = mapped_column(String(30), nullable=False)
    # status：active / inactive
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    user: Mapped[User] = relationship(back_populates="project_members")
    project: Mapped[Project] = relationship(back_populates="members")
