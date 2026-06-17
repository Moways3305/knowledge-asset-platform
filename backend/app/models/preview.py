"""预览凭证 ORM 模型。

仅一张表 preview_credentials，承载预览凭证签发记录。

安全：只存 token_hash（不可逆哈希），不存明文 token；credential_fingerprint 是
可对外的短指纹；preview_entry_url 是平台受控相对路径，不是对象存储签名 URL。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class PreviewCredential(Base):
    __tablename__ = "preview_credentials"
    __table_args__ = (
        Index("ix_preview_status_expires", "credential_status", "expires_at"),
        Index("ix_preview_asset_requester", "target_asset_id", "requester_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    target_asset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id"), nullable=False
    )
    target_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_asset_versions.id"), nullable=True
    )
    requester_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    preview_type: Mapped[str] = mapped_column(String(20), nullable=False)
    credential_status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    # 只存不可逆哈希，绝不存明文 token。
    token_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    # 可对外的短指纹（非 token、不可逆）。
    credential_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    # 平台受控相对路径，如 /api/v1/preview/{id}；非对象存储签名 URL。
    preview_entry_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # ONLYOFFICE 受控取件 token 的 sha256（明文仅一次性放进 Document Server 取件 URL，
    # 服务端只存哈希；过期随凭证 expires_at；**绝不**存明文 / 进响应 / 进审计）。
    fetch_token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
