"""Consultants' private delegations, with fenced recovery and identifier-only results."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class KnowledgeTask(Base):
    __tablename__ = "knowledge_agent_tasks"
    __table_args__ = (
        Index("ix_knowledge_tasks_owner", "user_id", "role", "library_key", "created_at"),
        Index("ix_knowledge_tasks_recovery", "status", "lease_until"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(30))
    library_key: Mapped[str] = mapped_column(String(60))
    instruction: Mapped[str] = mapped_column(String(600))
    status: Mapped[str] = mapped_column(String(24), default="queued")
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claim: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
