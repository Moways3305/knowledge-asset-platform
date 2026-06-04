"""部署 / 可观测端点（R8）。

- GET /health/ready：就绪探针（DB 连通；async 模式下 Redis 连通）。
- GET /health/config：**安全**配置诊断（只回 enabled/disabled 布尔 + provider 名 + 缺失项名，
  绝不回任何密钥 / 连接串 / URL / token / 内部标识）。
- GET /admin/ops/summary：admin 运营摘要（版本/环境 + 就绪 + Celery 模式 + 入库/通知/审计计数）。

安全红线：本模块任何响应**绝不**含连接串 / api_key / token / secret / 对象存储路径 /
WeKnora·Dify id / WeCom secret / ONLYOFFICE jwt / 预览取件 token / 业务正文。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.config import get_settings
from app.db.session import get_db
from app.models.audit import AuditEvent
from app.models.ingest import IngestTask
from app.models.lifecycle import NotificationRecord
from app.schemas.enums import (
    AuditLogType,
    CompanyRole,
    IngestStatus,
    NotificationChannel,
    NotificationStatus,
)
from app.schemas.permission import CallerContext
from app.services.llm_client import llm_enabled
from app.services.onlyoffice import onlyoffice_enabled
from app.services.wecom_client import wecom_enabled
from app.services.weknora_client import weknora_enabled

router = APIRouter(tags=["ops"])

_VERSION = "0.1.0"


async def _db_ready(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


async def _redis_ready() -> bool | None:
    """async 模式下检查 Redis；eager 模式返回 None（不需要 broker）。"""
    s = get_settings()
    if s.celery_task_always_eager:
        return None
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            s.celery_broker_url or s.redis_url, socket_connect_timeout=2, socket_timeout=2
        )
        try:
            await client.ping()
            return True
        finally:
            await client.aclose()
    except Exception:  # noqa: BLE001
        return False


@router.get("/health/ready")
async def health_ready(response: Response, session: AsyncSession = Depends(get_db)) -> dict:
    """就绪探针：DB 必须连通；async 模式下 Redis 也需连通。未就绪 → 503。"""
    db_ok = await _db_ready(session)
    redis_ok = await _redis_ready()
    ready = db_ok and (redis_ok is not False)
    if not ready:
        response.status_code = 503
    return {
        "status": "ready" if ready else "not_ready",
        "checks": {"database": db_ok, "redis": redis_ok},
    }


def _missing_config(s) -> list[str]:
    """已开启但缺关键值的配置项**名称**（仅名称，绝不含值）。"""
    missing: list[str] = []
    if s.onlyoffice_enabled and not s.onlyoffice_document_server_url:
        missing.append("ONLYOFFICE_DOCUMENT_SERVER_URL")
    if s.wecom_notify_enabled and not (s.wecom_corp_id and s.wecom_app_secret):
        missing.append("WECOM_CORP_ID/WECOM_APP_SECRET")
    return missing


@router.get("/health/config")
async def health_config() -> dict:
    """安全配置诊断：只回布尔 + provider 名 + 缺失项名，绝不回值/密钥/URL。"""
    s = get_settings()
    return {
        "app_env": s.app_env,
        "version": _VERSION,
        "integrations": {
            "weknora_enabled": weknora_enabled(),
            "llm_enabled": llm_enabled(),
            "llm_provider": s.llm_provider or None,  # provider 名（如 deepseek）安全，非密钥
            "wecom_enabled": wecom_enabled(),
            "wecom_notify_enabled": bool(s.wecom_notify_enabled),
            "onlyoffice_enabled": onlyoffice_enabled(),
            "celery_eager": bool(s.celery_task_always_eager),
        },
        "missing_config": _missing_config(s),
    }


def _require_admin(caller: CallerContext) -> None:
    from fastapi import HTTPException

    if CompanyRole.admin.value not in caller.active_company_roles:
        raise HTTPException(403, detail={"denied_reason": "ops_admin_required", "message": "仅 admin 可查看运营摘要"})


@router.get("/admin/ops/summary")
async def ops_summary(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """admin 运营摘要：安全计数信号（无业务正文 / 无内部标识 / 无密钥）。"""
    _require_admin(caller)
    s = get_settings()

    async def _count(stmt) -> int:
        return int((await session.execute(stmt)).scalar() or 0)

    ingest_counts = {}
    for status in (
        IngestStatus.processing, IngestStatus.pending_confirmation,
        IngestStatus.failed, IngestStatus.completed,
    ):
        ingest_counts[status.value] = await _count(
            select(func.count()).select_from(IngestTask).where(IngestTask.status == status.value)
        )
    pending_wecom = await _count(
        select(func.count()).select_from(NotificationRecord)
        .where(NotificationRecord.channel == NotificationChannel.wecom.value)
        .where(NotificationRecord.send_status == NotificationStatus.pending.value)
    )
    unprocessed_exc = await _count(
        select(func.count()).select_from(AuditEvent)
        .where(AuditEvent.log_type == AuditLogType.exception.value)
        .where(AuditEvent.is_processed.is_(False))
    )
    return {
        "app_env": s.app_env,
        "version": _VERSION,
        "db_ready": await _db_ready(session),
        "redis_ready": await _redis_ready(),
        "celery_eager": bool(s.celery_task_always_eager),
        "ingest": ingest_counts,
        "notifications": {"pending_wecom": pending_wecom},
        "audit": {"unprocessed_exceptions": unprocessed_exc},
    }
