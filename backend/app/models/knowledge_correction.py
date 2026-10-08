"""Reader corrections are workflow records, not public comments or knowledge text."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class KnowledgeCorrection(Base):
    __tablename__ = "knowledge_corrections"
    __table_args__ = (Index("ix_knowledge_corrections_asset_status", "asset_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("knowledge_assets.id"))
    reporter_user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="open")
    description: Mapped[str] = mapped_column(Text)
    resolution: Mapped[str | None] = mapped_column(Text)
    reported_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reported_fingerprint: Mapped[str] = mapped_column(String(64))
    resolved_fingerprint: Mapped[str | None] = mapped_column(String(64))
    resolved_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("knowledge_assets.id")
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
