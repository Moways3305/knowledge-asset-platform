"""KAP 内容生成模型持久化配置。

API 地址与 API key 只存 Fernet 密文；内部 UUID、密文均为 server-only。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class ContentGenerationModel(Base):
    __tablename__ = "content_generation_models"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # External LLMs are chat-only. Non-chat values may exist from the retired PBC-48 bridge;
    # they are preserved for rollback/data compatibility but excluded from external LLM APIs.
    capability_type: Mapped[str] = mapped_column(String(20), nullable=False, default="chat")
    # Retired bridge metadata. Kept nullable to preserve existing rows; runtime code does not
    # read, populate, or mutate this field after PBC-63.
    weknora_model_ref: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )
    base_url_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_test_succeeded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_test_failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Fixed safe category only; never stores an upstream message, response, URL, or credential.
    last_error_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ContentGenerationSettings(Base):
    """平台单例设置。存在此行即表示产品配置已接管，不再回退 LLM_*。"""

    __tablename__ = "content_generation_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    default_model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("content_generation_models.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
