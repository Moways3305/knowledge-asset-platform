"""Library-owned child directories, independent of global policy drafts."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.utils import utc_now


class KnowledgeDirectory(Base):
    __tablename__ = "knowledge_directories"
    __table_args__ = (UniqueConstraint("library_key", "parent_key", "normalized_name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    directory_key: Mapped[str] = mapped_column(String(100), unique=True)
    library_key: Mapped[str] = mapped_column(String(50))
    scope: Mapped[str] = mapped_column(String(20))
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("projects.id"))
    parent_key: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(80))
    normalized_name: Mapped[str] = mapped_column(String(80))
    default_confidentiality: Mapped[str] = mapped_column(String(10))
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
