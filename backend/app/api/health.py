"""Health check endpoint.

Liveness only — does not touch the database or any external system.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.config import get_settings
from app.core.trace import get_trace_id

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Return basic liveness info plus the request trace_id."""
    settings = get_settings()
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
        "trace_id": get_trace_id(request),
    }
