"""SQLAlchemy declarative base.

IMPLEMENT-00 establishes the Base only. No business tables are defined here.
Business models arrive in later IMPLEMENT tasks and must follow the data model
design in `docs/backend/01-数据模型DATA_MODEL.md`.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all future ORM models."""

    pass
