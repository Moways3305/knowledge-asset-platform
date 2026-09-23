"""Deployment-linked release drafts, administrator announcements and read receipts."""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class ReleaseNote(Base):
    __tablename__ = "release_notes"
    __table_args__ = (
        Index("ix_release_notes_published", "published_at", "notify_users"),
        UniqueConstraint("source_commit", name="uq_release_notes_source_commit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    entries: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    notify_users: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    source_commit: Mapped[str | None] = mapped_column(String(40))
    previous_commit: Mapped[str | None] = mapped_column(String(40))
    manifest_digest: Mapped[str | None] = mapped_column(String(64))
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReleaseNoteRead(Base):
    __tablename__ = "release_note_reads"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"), primary_key=True)
    release_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("release_notes.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
