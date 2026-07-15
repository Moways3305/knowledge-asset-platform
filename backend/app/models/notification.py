"""Business-user notification inbox facts.

This table is intentionally separate from ``notification_records``. The latter is an
admin operations channel; mixing business review events into it would disclose business
activity to pure administrators.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class BusinessNotification(Base):
    """A safe, recipient-scoped pointer to an independently authorized business target."""

    __tablename__ = "business_notifications"
    __table_args__ = (
        UniqueConstraint(
            "recipient_user_id", "dedup_key", name="uq_business_notification_recipient_event"
        ),
        Index(
            "ix_business_notifications_recipient_created",
            "recipient_user_id",
            "created_at",
        ),
        Index(
            "ix_business_notifications_recipient_unread",
            "recipient_user_id",
            "read_at",
        ),
        Index("ix_business_notifications_delivery", "channel", "delivery_status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    target_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    # Used only to re-check membership before reads/delivery; never returned by the API.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True
    )
    dedup_key: Mapped[str] = mapped_column(String(140), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="in_app")
    delivery_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    delivery_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
