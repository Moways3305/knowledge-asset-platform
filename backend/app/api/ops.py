"""部署 / 可观测端点。

- GET /health/ready：就绪探针（DB 连通；async 模式下 Redis 连通）。
- GET /health/config：**安全**配置诊断（只回 enabled/disabled 布尔 + provider 名 + 缺失项名，
  绝不回任何密钥 / 连接串 / URL / token / 内部标识）。
- GET /admin/ops/summary：admin 运营摘要（版本/环境 + 就绪 + Celery 模式 + 入库/通知/审计计数）。

安全红线：本模块任何响应**绝不**含连接串 / api_key / token / secret / 对象存储路径 /
WeKnora·Dify id / WeCom secret / ONLYOFFICE jwt / 预览取件 token / 业务正文。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable
from typing import cast
from urllib.parse import urlsplit

from fastapi import APIRouter, Cookie, Depends, Request, Response
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_caller_context
from app.core.config import (
    get_settings,
    session_cookie_secure_misconfigured,
)
from app.core.logging import safe_log_exception
from app.core.trace import get_trace_id
from app.db.session import get_db
from app.models.audit import AuditEvent
from app.models.identity import Project, User
from app.models.indexing_job import IndexingOperationJob
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.lifecycle import NotificationRecord
from app.schemas.auth_security import (
    AuthSecurityOverviewResponse,
    AuthUnlockRequest,
    AuthUnlockResponse,
)
from app.schemas.enums import (
    AssetStatus,
    AuditAction,
    AuditLogType,
    CompanyRole,
    IngestStatus,
    NotificationChannel,
    NotificationStatus,
)
from app.schemas.indexing_ops import (
    IndexingHealthResponse,
    IndexingJobListResponse,
    IndexingJobSummary,
    IndexingReparseRequest,
    IndexingRetryRequest,
)
from app.schemas.permission import CallerContext
from app.schemas.session_ops import (
    SessionRevokeRequest,
    SessionRevokeResponse,
    UserSessionsResponse,
)
from app.schemas.wecom_identity import ReconcileRequest, ReconcileResponse
from app.services import audit as audit_service
from app.services import (
    auth_security_ops,
    error_catalog,
    generation_models,
    indexing_health,
    session_revocation,
    wecom_identity,
    weknora_defaults,
)
from app.services import indexing_ops as indexing_ops_service
from app.services.auth_session import SESSION_COOKIE_NAME
from app.services.llm_client import llm_enabled
from app.services.onlyoffice import onlyoffice_enabled
from app.services.storage import LocalFileStorage, get_storage
from app.services.wecom_client import get_wecom_oauth_client, wecom_enabled
from app.services.weknora_client import get_weknora_client, weknora_enabled

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["ops"])

_VERSION = "0.1.0"


async def _db_ready(session: AsyncSession) -> bool:
    try:
        await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001
        safe_log_exception(
            _logger, "health_db_check_failed", exc, include_summary=False, level=logging.WARNING
        )
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
            # redis-py 的 ping() 类型为 Awaitable[bool] | bool（sync/async 共用签名）；
            # async 客户端下实为 awaitable，cast 收敛类型，运行时无变化。
            await cast("Awaitable[bool]", client.ping())
            return True
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        safe_log_exception(
            _logger, "health_redis_check_failed", exc, include_summary=False, level=logging.WARNING
        )
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


def _http_origin(value: str) -> str | None:
    """Return a normalized HTTP(S) origin without exposing it to callers."""
    try:
        parsed = urlsplit((value or "").strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
            return None
        if parsed.username or parsed.password:
            return None
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    except ValueError:
        return None


def _origin_only(value: str) -> bool:
    try:
        parsed = urlsplit((value or "").strip())
        return bool(
            _http_origin(value)
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


def _onlyoffice_config_status(s) -> dict[str, bool]:
    document_origin = _http_origin(s.onlyoffice_document_server_url)
    csp_origin = _http_origin(s.onlyoffice_origin)
    internal_base = _http_origin(s.onlyoffice_internal_base_url)
    return {
        "document_server_origin_valid": bool(
            document_origin and _origin_only(s.onlyoffice_document_server_url)
        ),
        "internal_base_configured": bool(internal_base),
        "csp_origin_valid": bool(csp_origin and _origin_only(s.onlyoffice_origin)),
        "browser_origin_matches": bool(document_origin and csp_origin == document_origin),
    }


def _missing_config(
    s,
    *,
    default_embedding_ok: bool,
    default_chat_ok: bool,
    generation_product_configured: bool,
) -> list[str]:
    """已开启但缺关键值的配置项**名称**（仅名称，绝不含值）。

    PBC-38：WeKnora 启用时检查的是**平台默认 embedding 模型**（DB `weknora_default_models`，
    由 `default_embedding_ok` 传入），而非已废弃的 `WEKNORA_EMBEDDING_MODEL_ID`（见 .env.example）。
    """
    missing: list[str] = []
    # WeKnora 已启用（base_url + api_key）但未配置平台默认 embedding → 建库 fail-closed。
    if weknora_enabled() and not default_embedding_ok:
        missing.append("WEKNORA_DEFAULT_EMBEDDING_MODEL")
    if weknora_enabled() and not default_chat_ok:
        missing.append("WEKNORA_DEFAULT_KNOWLEDGE_QA_MODEL")
    # 模型配置中心的 model_ref HMAC key 缺失 → 生产应显式配置（dev 回退稳定常量）。
    if weknora_enabled() and not (s.weknora_model_ref_secret or "").strip():
        missing.append("WEKNORA_MODEL_REF_SECRET")
    if s.onlyoffice_enabled and not s.onlyoffice_document_server_url:
        missing.append("ONLYOFFICE_DOCUMENT_SERVER_URL")
    if s.onlyoffice_enabled and not s.onlyoffice_internal_base_url:
        missing.append("ONLYOFFICE_INTERNAL_BASE_URL")
    if s.onlyoffice_enabled and not s.onlyoffice_origin:
        missing.append("ONLYOFFICE_ORIGIN")
    if s.wecom_notify_enabled and not (s.wecom_corp_id and s.wecom_app_secret):
        missing.append("WECOM_CORP_ID/WECOM_APP_SECRET")
    if generation_product_configured and not (s.generation_model_encryption_key or "").strip():
        missing.append("GENERATION_MODEL_ENCRYPTION_KEY")
    return missing


def _production_blockers(
    s,
    *,
    default_embedding_ok: bool,
    default_chat_ok: bool,
    generation_product_configured: bool,
) -> list[str]:
    """生产**硬阻断**项名：必须修复才能安全上线。仅 prod 评估，否则空——
    本地/测试默认 eager 等不视为失败。只回安全项名，绝不回值/密钥/URL/内部 id。"""
    if s.app_env != "prod":
        return []
    blockers: list[str] = []
    # 1) 生产必须接真实 worker：eager 同步执行会让长作业阻塞请求、丢异步语义。
    if s.celery_task_always_eager:
        blockers.append("CELERY_TASK_ALWAYS_EAGER")
    # 2) 会话 cookie 在 prod 运行时已被强制 Secure；若运维仍显式注入 false，诚实报阻断。
    if session_cookie_secure_misconfigured(s):
        blockers.append("SESSION_COOKIE_SECURE")
    # 2b) 登录失败风控 HMAC secret：prod 必须显式配置（否则回退常量可被预测）。
    if not (s.auth_attempt_hash_secret or "").strip():
        blockers.append("AUTH_ATTEMPT_HASH_SECRET")
    # 2c) CSRF token HMAC secret：prod 必须显式配置（否则签名 key 可预测）。
    if not (s.csrf_token_secret or "").strip():
        blockers.append("CSRF_TOKEN_SECRET")
    # 3) WeKnora 启用但建库 / model_ref 关键项缺失 → KB 不可用 / model_ref 不稳定。
    #    PBC-38：建库 embedding 来自平台默认模型配置（DB），不再以 WEKNORA_EMBEDDING_MODEL_ID
    #    （已废弃 legacy，见 .env.example）作为生产阻断项。
    if weknora_enabled():
        if not default_embedding_ok:
            blockers.append("WEKNORA_DEFAULT_EMBEDDING_MODEL")
        if not default_chat_ok:
            blockers.append("WEKNORA_DEFAULT_KNOWLEDGE_QA_MODEL")
        if not (s.weknora_model_ref_secret or "").strip():
            blockers.append("WEKNORA_MODEL_REF_SECRET")
    # 4) ONLYOFFICE 启用：缺 Document Server URL → 预览不可用；缺 JWT secret → 生产
    #    Document Server 通常强制 JWT，未签名 config 会被拒/不安全，故 prod 视为阻断。
    if s.onlyoffice_enabled:
        status = _onlyoffice_config_status(s)
        if not (s.onlyoffice_document_server_url or "").strip():
            blockers.append("ONLYOFFICE_DOCUMENT_SERVER_URL")
        elif not status["document_server_origin_valid"]:
            blockers.append("ONLYOFFICE_DOCUMENT_SERVER_URL_ORIGIN")
        if not (s.onlyoffice_internal_base_url or "").strip():
            blockers.append("ONLYOFFICE_INTERNAL_BASE_URL")
        elif not status["internal_base_configured"]:
            blockers.append("ONLYOFFICE_INTERNAL_BASE_URL_INVALID")
        if not (s.onlyoffice_origin or "").strip():
            blockers.append("ONLYOFFICE_ORIGIN")
        elif not status["csp_origin_valid"]:
            blockers.append("ONLYOFFICE_ORIGIN_INVALID")
        elif not status["browser_origin_matches"]:
            blockers.append("ONLYOFFICE_ORIGIN_MISMATCH")
        if not (s.onlyoffice_jwt_secret or "").strip():
            blockers.append("ONLYOFFICE_JWT_SECRET")
    # 5) 企微通知启用但缺 corp/app secret 项 → 通知无法真实下发。
    if s.wecom_notify_enabled and not (s.wecom_corp_id and s.wecom_app_secret):
        blockers.append("WECOM_CORP_ID/WECOM_APP_SECRET")
    if generation_product_configured and not (s.generation_model_encryption_key or "").strip():
        blockers.append("GENERATION_MODEL_ENCRYPTION_KEY")
    return blockers


def _production_warnings(s, *, external_llm_configured: bool) -> list[str]:
    """生产**软提醒**项名：不阻断上线但建议运维确认。仅安全项名。"""
    warnings: list[str] = []
    # KAP 内容生成模型未配置 → 标题/摘要/标签建议降级为确定性草稿，系统仍可用。
    if not external_llm_configured:
        warnings.append("EXTERNAL_LLM_NOT_CONFIGURED")
    # WeKnora 未配置 → 检索 / 索引降级（dev 可接受，生产一般应接真实底座）。
    if not weknora_enabled():
        warnings.append("WEKNORA_NOT_CONFIGURED")
    return warnings


@router.get("/health/config")
async def health_config(session: AsyncSession = Depends(get_db)) -> dict:
    """安全配置诊断：只回布尔 + provider 名 + 缺失项名 + 生产就绪信号，绝不回值/密钥/URL。

    PBC-38：平台默认 embedding 模型存 DB（weknora_default_models），故需 DB 会话判定其是否已配。
    """
    s = get_settings()
    defaults = await weknora_defaults.get_defaults(session)
    generation_product_configured = await generation_models.product_configuration_exists(session)
    external_llm_configured = await generation_models.generation_model_configured(session)
    default_embedding_ok = bool(defaults and (defaults.default_embedding_model_id or "").strip())
    default_chat_ok = bool(defaults and (defaults.default_chat_model_id or "").strip())
    blockers = _production_blockers(
        s,
        default_embedding_ok=default_embedding_ok,
        default_chat_ok=default_chat_ok,
        generation_product_configured=generation_product_configured,
    )
    return {
        "app_env": s.app_env,
        "version": _VERSION,
        "integrations": {
            "weknora_enabled": weknora_enabled(),
            "weknora_foundation_defaults_configured": default_embedding_ok and default_chat_ok,
            "llm_enabled": llm_enabled(),
            "external_llm_configured": external_llm_configured,
            # Compatibility alias for existing operational dashboards.
            "kap_generation_model_configured": external_llm_configured,
            "llm_provider": s.llm_provider or None,  # provider 名（如 deepseek）安全，非密钥
            "wecom_enabled": wecom_enabled(),
            "wecom_notify_enabled": bool(s.wecom_notify_enabled),
            "onlyoffice_enabled": onlyoffice_enabled(),
            "onlyoffice_config": _onlyoffice_config_status(s),
            "celery_eager": bool(s.celery_task_always_eager),
        },
        "missing_config": _missing_config(
            s,
            default_embedding_ok=default_embedding_ok,
            default_chat_ok=default_chat_ok,
            generation_product_configured=generation_product_configured,
        ),
        # 生产就绪：当前实例为 prod 部署且无硬阻断项。非 prod 恒为 False（按定义不是生产
        # 部署），但仍返回 warnings 供运维预览；blockers 仅 prod 评估，避免误判本地开发。
        "production_ready": s.app_env == "prod" and not blockers,
        "production_blockers": blockers,
        "production_warnings": _production_warnings(
            s, external_llm_configured=external_llm_configured
        ),
    }


def _require_admin(caller: CallerContext) -> None:
    from fastapi import HTTPException

    if CompanyRole.admin.value not in caller.active_company_roles:
        raise HTTPException(
            403,
            detail={"denied_reason": "ops_admin_required", "message": "仅 admin 可查看运营摘要"},
        )


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
        IngestStatus.processing,
        IngestStatus.pending_confirmation,
        IngestStatus.failed,
        IngestStatus.completed,
    ):
        ingest_counts[status.value] = await _count(
            select(func.count()).select_from(IngestTask).where(IngestTask.status == status.value)
        )
    pending_wecom = await _count(
        select(func.count())
        .select_from(NotificationRecord)
        .where(NotificationRecord.channel == NotificationChannel.wecom.value)
        .where(NotificationRecord.send_status == NotificationStatus.pending.value)
    )
    unprocessed_exc = await _count(
        select(func.count())
        .select_from(AuditEvent)
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


def _require_ops_viewer(caller: CallerContext) -> None:
    """索引运维视图：admin（系统运维）或业务治理角色（boss / 咨询总监）可看。"""
    from fastapi import HTTPException

    if CompanyRole.admin.value in caller.active_company_roles or caller.can_discover_l5:
        return
    raise HTTPException(
        403, detail={"denied_reason": "ops_viewer_required", "message": "无权查看索引运维视图"}
    )


@router.get("/admin/ops/indexing")
async def ops_indexing(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> dict:
    """索引运维面板：安全索引计数 + 最近失败列表。

    安全：**绝不**返回 kb_id / doc_id / api_key / storage_ref / source_file_ref / 原文。
    标题边界：业务治理角色可见真实 title；纯 admin（无业务发现权）→ 标题隐藏。
    """
    _require_ops_viewer(caller)
    show_title = caller.can_discover_l5  # 仅业务治理角色看真实标题；纯 admin 隐藏。

    active_non_deleted = (
        KnowledgeAssetVersion.version_status == "active",
        KnowledgeAsset.asset_status != AssetStatus.deleted.value,
    )

    counts = await indexing_health.indexing_counts(session)

    # 最近失败资产（安全摘要，最多 20 条）。
    rows = (
        await session.execute(
            select(KnowledgeAsset, KnowledgeAssetVersion)
            .join(KnowledgeAssetVersion, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            .where(*active_non_deleted, KnowledgeAssetVersion.index_status == "index_failed")
            .order_by(KnowledgeAsset.updated_at.desc())
            .limit(20)
        )
    ).all()
    project_ids = {a.project_id for a, _v in rows if a.project_id}
    owner_ids = {a.owner_user_id for a, _v in rows if a.owner_user_id}
    pmap: dict = {}
    omap: dict = {}
    if project_ids:
        for pid, pname in (
            await session.execute(
                select(Project.id, Project.name).where(Project.id.in_(project_ids))
            )
        ).all():
            pmap[pid] = pname
    if owner_ids:
        for uid, uname in (
            await session.execute(select(User.id, User.name).where(User.id.in_(owner_ids)))
        ).all():
            omap[uid] = uname

    active_target_ids = set(
        (
            await session.execute(
                select(IndexingOperationJob.target_asset_id).where(
                    IndexingOperationJob.target_asset_id.is_not(None),
                    IndexingOperationJob.operation_type == "retry_index",
                    IndexingOperationJob.status.in_(("queued", "running")),
                )
            )
        ).scalars()
    )
    diagnostic_counts = {key: 0 for key in error_catalog.DIAGNOSTIC_LABELS}
    grouped_codes = (
        await session.execute(
            select(KnowledgeAssetVersion.index_error_code, func.count())
            .join(KnowledgeAsset, KnowledgeAssetVersion.asset_id == KnowledgeAsset.id)
            .where(*active_non_deleted, KnowledgeAssetVersion.index_status == "index_failed")
            .group_by(KnowledgeAssetVersion.index_error_code)
        )
    ).all()
    for code, count in grouped_codes:
        category, _label = error_catalog.diagnostic(code)
        diagnostic_counts[category] += int(count or 0)

    recent_failed = []
    for a, v in rows:
        # 安全目录 code：历史脏 code 也归一，不外显原始上游 code。
        scode = error_catalog.safe_code(v.index_error_code)
        info = error_catalog.get_error(scode)
        diagnostic_category, diagnostic_label = error_catalog.diagnostic(scode)
        retry_eligible = (
            error_catalog.targeted_retry_eligible(scode) and a.id not in active_target_ids
        )
        recent_failed.append(
            {
                "retry_target": (
                    indexing_ops_service.issue_targeted_retry_token(a.id)
                    if retry_eligible
                    else None
                ),
                "title": a.title if show_title else "（业务资产标题已隐藏）",
                "scope": a.scope,
                "project_name": (pmap.get(a.project_id) if show_title and a.project_id else None),
                "owner_name": (omap.get(a.owner_user_id) if show_title else None),
                "index_status": v.index_status,
                "index_error_code": scode,
                # 用户态文案（与详情页一致，按目录派生，不外显旧/上游脏文案）。
                "index_error_message": info.user_message,
                # 运营态诊断（admin/运营可见；含配置项名，绝不含值/内部 id/secret）。
                "operator_error_message": info.operator_message,
                "remediation_hint": info.remediation_hint,
                "severity": info.severity,
                "diagnostic_category": diagnostic_category,
                "diagnostic_label": diagnostic_label,
                "retry_eligible": retry_eligible,
                "updated_at": a.updated_at.isoformat() if a.updated_at else None,
            }
        )

    return {
        "counts": counts,
        "recent_failed": recent_failed,
        "diagnostic_counts": diagnostic_counts,
        "title_visible": show_title,
    }


@router.get("/admin/ops/indexing/health", response_model=IndexingHealthResponse)
async def ops_indexing_health(
    window_hours: int = 24,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> IndexingHealthResponse:
    _require_ops_viewer(caller)
    return await indexing_health.get_health(session, window_hours=window_hours)


@router.post(
    "/admin/ops/indexing/failures/{operation_target}/retry",
    response_model=IndexingJobSummary,
    status_code=202,
)
async def ops_indexing_target_retry(
    operation_target: str,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    weknora=Depends(get_weknora_client),
) -> IndexingJobSummary:
    return await indexing_ops_service.create_targeted_retry_from_operation_target(
        session,
        caller,
        operation_target,
        weknora=weknora,
        storage=storage,
        trace_id=get_trace_id(request),
    )


@router.post("/admin/ops/indexing/retry", response_model=IndexingJobSummary, status_code=202)
async def ops_indexing_retry(
    req: IndexingRetryRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    weknora=Depends(get_weknora_client),
) -> IndexingJobSummary:
    """批量 retry-index：对筛选出的 index_failed / skipped / not_indexed 资产入队
    后台重试。仅 admin / 业务治理角色；202 + 安全 job 摘要，不在请求内逐条跑完（eager 例外）。
    绝不外泄 kb_id / doc_id / storage_ref / 原文。"""
    return await indexing_ops_service.create_retry_job(
        session,
        caller,
        req,
        weknora=weknora,
        storage=storage,
        trace_id=get_trace_id(request),
    )


@router.post("/admin/ops/indexing/reparse", response_model=IndexingJobSummary, status_code=202)
async def ops_indexing_reparse(
    req: IndexingReparseRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    storage: LocalFileStorage = Depends(get_storage),
    weknora=Depends(get_weknora_client),
) -> IndexingJobSummary:
    """显式 reparse：对已进底座但解析异常（failed / pending / processing）的资产入队
    重新解析（受控重传刷新底座解析）。仅 admin / 业务治理角色；202 + 安全 job 摘要。"""
    return await indexing_ops_service.create_reparse_job(
        session,
        caller,
        req,
        weknora=weknora,
        storage=storage,
        trace_id=get_trace_id(request),
    )


@router.get("/admin/ops/indexing/jobs", response_model=IndexingJobListResponse)
async def ops_indexing_jobs(
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> IndexingJobListResponse:
    """最近索引运维作业列表：仅安全统计 + 安全筛选条件 + 安全错误文案；
    绝不返回所处理资产的标题 / 原文 / 文件名 / WeKnora id / 存储引用。"""
    return await indexing_ops_service.list_jobs(session, caller)


# ---------------------------------------------------------------------------
# 登录风控运维：admin-only 风控面板 + 手动解除 identifier 短时锁定
# ---------------------------------------------------------------------------
@router.get("/admin/ops/auth-security", response_model=AuthSecurityOverviewResponse)
async def ops_auth_security(
    window_minutes: int | None = None,
    limit: int | None = None,
    result: str | None = None,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> AuthSecurityOverviewResponse:
    """登录风控运维聚合。

    返回近期 failed/locked/rate_limited/success/unlocked 计数 + 最近事件安全视图（不可逆
    hash 前缀 / 安全用户元数据）。**绝不**返回 raw email / raw IP / 完整 hash / password /
    token / cookie。只读，不写审计（避免读放大）。"""
    _require_admin(caller)
    return await auth_security_ops.get_overview(
        session, window_minutes=window_minutes, limit=limit, result=result
    )


@router.post("/admin/ops/auth-security/unlock", response_model=AuthUnlockResponse)
async def ops_auth_security_unlock(
    body: AuthUnlockRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
) -> AuthUnlockResponse:
    """手动解除 identifier 短时锁定。写 `result="unlocked"` reset anchor + `auth.lockout_unlocked` 审计；
    不绕过密码校验、不建会话、不改密码、不重置 IP rate limit。"""
    _require_admin(caller)
    return await auth_security_ops.unlock_identifier(
        session, caller, body=body, trace_id=get_trace_id(request)
    )


# ---------------------------------------------------------------------------
# 平台会话运维：admin-only 安全会话查看 + 强制撤销
# ---------------------------------------------------------------------------
@router.get("/admin/ops/sessions/users/{user_id}", response_model=UserSessionsResponse)
async def ops_user_sessions(
    user_id: uuid.UUID,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    kap_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> UserSessionsResponse:
    """查看某用户的平台会话安全元数据。

    只返回安全 `session_id`（非 token hash）+ login_method + 时间 + 撤销状态 +
    is_current_actor_session；**绝不**返回 token / token_hash / cookie / ip / device_info。"""
    _require_admin(caller)
    return await session_revocation.list_sessions(
        session, user_id, current_hash=session_revocation.current_token_hash(kap_session)
    )


@router.post("/admin/ops/sessions/users/{user_id}/revoke", response_model=SessionRevokeResponse)
async def ops_revoke_user_sessions(
    user_id: uuid.UUID,
    body: SessionRevokeRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    kap_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
) -> SessionRevokeResponse:
    """强制撤销某用户的活动平台会话。可选 `preserve_current_session`（仅当目标==当前 admin 自己时保留
    本会话）。写 `auth.sessions_revoked` 审计。**不**返回 / 记录 token / cookie 值。"""
    _require_admin(caller)
    exclude = None
    if body.preserve_current_session and user_id == caller.user_id:
        exclude = session_revocation.current_token_hash(kap_session)
    revoked, revoked_at = await session_revocation.revoke_user_sessions(
        session, user_id, exclude_token_hash=exclude
    )
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.auth_sessions_revoked.value,
        trace_id=get_trace_id(request),
        target_type="user",
        target_id=user_id,
        extra={
            "target_user_id": str(user_id),
            "revoked_count": revoked,
            "trigger": "admin_manual",
            "preserved_current_session": exclude is not None,
            **({"reason": body.reason[:200]} if body.reason else {}),
        },
    )
    await session.commit()
    return SessionRevokeResponse(
        ok=True,
        user_id=user_id,
        revoked_count=revoked,
        revoked_at=revoked_at,
        preserved_current_session=exclude is not None,
    )


# ---------------------------------------------------------------------------
# 企微身份生命周期对账：admin-only。失效成员 → 停用平台用户 + 撤销会话
# ---------------------------------------------------------------------------
@router.post("/admin/ops/wecom-identity/reconcile", response_model=ReconcileResponse)
async def ops_wecom_identity_reconcile(
    body: ReconcileRequest,
    request: Request,
    caller: CallerContext = Depends(get_caller_context),
    session: AsyncSession = Depends(get_db),
    oauth=Depends(get_wecom_oauth_client),
) -> ReconcileResponse:
    """对账绑定企微的平台用户。

    失效（禁用/删除/未激活/未知）成员 → 停用平台用户 + 撤销活动会话 + 安全审计。`dry_run` 只预演。
    响应只含安全聚合 + 安全 item（**不**含 raw wecom_user_id / 通讯录档案 / token / 上游 errmsg）。"""
    _require_admin(caller)
    return await wecom_identity.reconcile(
        session,
        caller,
        oauth,
        user_id=body.user_id,
        limit=body.limit,
        dry_run=body.dry_run,
        trace_id=get_trace_id(request),
    )
