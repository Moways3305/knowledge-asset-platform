"""DB / 模型层通用小工具。"""

from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> datetime:
    """当前 UTC 时间（aware）。统一各 model / service 的时间戳来源，取代散落的 `_now()`。"""
    return datetime.now(timezone.utc)
