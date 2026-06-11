"""SQLAlchemy 声明式基类。

定义所有 ORM 模型共用的 Base。
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base for all future ORM models."""

    pass

