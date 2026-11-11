"""Durable scheduled scan cycles; row locks live for one bounded transaction."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class GovernanceScanRun(Base):
    __tablename__ = "governance_scan_runs"

    name: Mapped[str] = mapped_column(String(20), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
