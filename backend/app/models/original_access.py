"""原文访问申请与授权 ORM 模型。

两张表：
- original_access_requests：原文访问申请（pending/approved/rejected/cancelled）。
- access_grants：审批通过后生成的可撤销、可过期、可审计的原文访问授权。

运行时权限（`decide()` 原文层）统一读取 active（未过期、未撤销）access_grants 作为放行事实。

安全：表只存安全枚举 / UUID / 时间 / 安全文本（reason/review_note）；绝不存原文 /
storage_ref / source_file_ref / URL / token / WeKnora id / provider 内部标识。

并发约束（部分唯一索引，PG / SQLite 兼容）：
- 同一 (grantee, asset, grant_type) 至多一个 active grant。
- 同一 (requester, asset) 至多一个 pending request。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class OriginalAccessRequest(Base):
    __tablename__ = "original_access_requests"
    __table_args__ = (
        Index(
            "uq_oar_one_pending",
            "requester_user_id",
            "asset_id",
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_oar_asset_status", "asset_id", "status"),
        Index("ix_oar_reviewer_status", "reviewer_user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    requester_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    # 本任务固定 raw/original 层（不为摘要层制造流程）。
    requested_access_layer: Mapped[str] = mapped_column(
        String(20), nullable=False, default="original"
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending / approved / rejected / cancelled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    reviewer_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class AccessGrant(Base):
    __tablename__ = "access_grants"
    __table_args__ = (
        Index(
            "uq_grant_one_active",
            "grantee_user_id",
            "asset_id",
            "grant_type",
            unique=True,
            sqlite_where=text("status = 'active'"),
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_grant_grantee_asset_status", "grantee_user_id", "asset_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    grantee_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), nullable=False)
    grant_type: Mapped[str] = mapped_column(String(30), nullable=False, default="original_access")
    source_request_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("original_access_requests.id"), nullable=True
    )
    granted_by_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    # active / revoked / expired
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
