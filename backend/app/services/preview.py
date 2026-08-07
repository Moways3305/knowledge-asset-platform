"""预览凭证服务。

签发逻辑复用集中权限服务 `app.services.permission`，不重写权限矩阵。
只签发 full（拥有 original 层权限时）；原文层判断会叠加 active access_grant
（审批通过的原文授权运行时放行），无授权时拒绝 `original_requires_request`（不签 summary_only）。

安全：只存 token_hash（sha256），不返回明文 token；preview_entry_url 为平台
受控相对路径；不触碰对象存储 / 文件流 / ONLYOFFICE。approve/issue 不写 audit_events。
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.utils import utc_now
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.preview import PreviewCredential
from app.schemas.enums import (
    AlertSeverity,
    AuditAction,
    AuditLogType,
    AuditRiskLevel,
    ConfidentialityLevel,
    CredentialStatus,
    PreviewType,
)
from app.schemas.permission import AccessChannel, AccessLayer, CallerContext, DeniedReason
from app.schemas.preview import (
    PreviewEntryResponse,
    PreviewIssueResponse,
)
from app.services import audit as audit_service
from app.services import original_access
from app.services.onlyoffice import (
    OnlyOfficeError,
    build_view_config,
    onlyoffice_enabled,
    resolve_doc_type,
)
from app.services.permission import decide
from app.services.permission_rules import load_access_policy
from app.services.storage import LocalFileStorage, safe_filename

# 默认预览凭证有效期。
PREVIEW_TTL_MINUTES = 30
_INACTIVE_STATUSES = {"processing", "archived", "deprecated", "deleted"}

# 扩展名 → 轻量渲染类型；不在此表且 ONLYOFFICE 支持的类型归 office 兜底。
_LIGHT_RENDER_TYPES = {
    "pdf": "pdf",
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "gif": "image",
    "webp": "image",
    "svg": "image",
    "bmp": "image",
    "md": "markdown",
    "markdown": "markdown",
    "txt": "text",
    "csv": "text",
    "json": "text",
    "log": "text",
}


def _render_type_for(file_name: str) -> str | None:
    """按扩展名决定预览渲染类型：pdf / image / markdown / text / office / None（不支持）。"""
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in (file_name or "") else ""
    light = _LIGHT_RENDER_TYPES.get(ext)
    if light is not None:
        return light
    return "office" if resolve_doc_type(file_name) is not None else None


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _resolve_original(
    session: AsyncSession, asset_id: uuid.UUID
) -> tuple[str, str, str | None] | None:
    """解析资产原文的平台存储引用（server-only）。返回 (storage_ref, file_name, mime)。

    经入库任务回链（IngestTask.result_asset_id）取得字节存储引用——这是 server-only 内部
    引用，**只在后端取件时用，绝不外泄**。无入库回链（如纯 seed 资产）→ None。
    """
    row = (
        await session.execute(
            select(
                IngestTask.source_file_ref,
                IngestTask.source_file_name,
                IngestTask.source_file_mime_type,
            )
            .where(IngestTask.result_asset_id == asset_id)
            .where(IngestTask.source_file_ref.is_not(None))
            .order_by(IngestTask.created_at.desc())
            .limit(1)
        )
    ).first()
    if row is None or not row[0]:
        return None
    return str(row[0]), str(row[1] or "document"), (row[2] or None)


def _denied(status_code: int, reason: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"denied_reason": reason, "message": message}
    )


def _as_aware(dt: datetime) -> datetime:
    """把可能为 naive 的时间戳视作 UTC（SQLite 读回为 naive，PostgreSQL 为 aware）。"""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def issue_preview(
    session: AsyncSession,
    caller: CallerContext,
    asset_id: uuid.UUID,
    version_id: uuid.UUID | None,
    trace_id: str | None,
) -> PreviewIssueResponse:
    """签发预览凭证：拥有 original 层权限时签发 full，否则拒绝。"""
    if not caller.is_business_user:
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value,
            trace_id=trace_id,
            target_type="knowledge_asset",
            target_id=asset_id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "denied_reason": "admin_business_permission_denied",
                "attempted": "preview.issue",
            },
        )
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可申请预览")

    asset = (
        await session.execute(select(KnowledgeAsset).where(KnowledgeAsset.id == asset_id))
    ).scalar_one_or_none()
    not_found = _denied(404, "knowledge_asset_not_found", "知识资产不存在或不可见")
    if asset is None:
        raise not_found

    # 发现层判断：不可发现的资产不泄露存在（L5 / 他人 personal / archived）。
    # L1/L2 原文默认放行由运行时 policy 决定。
    policy = await load_access_policy(session)
    d = decide(caller, asset, AccessLayer.discovery, policy=policy)
    if not d.allowed:
        if d.denied_reason == DeniedReason.user_inactive:
            raise _denied(403, DeniedReason.user_inactive.value, "用户已停用")
        if d.denied_reason == DeniedReason.asset_not_active:
            # archived / deprecated：直接拒绝（未实现归档受控预览）。
            raise _denied(403, "asset_not_active", "资产已归档/废弃，不可预览")
        # l5_not_discoverable / personal_asset_not_owned → 表现为不存在
        raise not_found

    # 原文层判断：human 渠道（A4 仅限制 agent，不阻 human preview）。
    # 叠加 active access_grant（审批通过的原文授权）后再判，运行时统一口径。
    has_grant = await original_access.has_active_grant(session, caller.user_id, asset.id)
    o = decide(
        caller,
        asset,
        AccessLayer.original,
        channel=AccessChannel.human,
        has_original_grant=has_grant,
        policy=policy,
    )
    if not o.allowed:
        # 无 original 权限：不签 summary_only，统一引导到原文访问申请。
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.preview_denied.value,
            trace_id=trace_id,
            target_type="knowledge_asset",
            target_id=asset.id,
            extra={
                "denied_reason": "original_requires_request",
                "confidentiality_level": asset.confidentiality_level,
            },
            project_id=asset.project_id,
        )
        raise _denied(
            403, "original_requires_request", "无原文层权限，请先发起原文访问申请或等待审批通过"
        )

    # version_id 校验：为空用当前版本；非空必须存在、属于本资产且 active。
    if version_id is None:
        target_version_id = asset.current_version_id
    else:
        version = (
            await session.execute(
                select(KnowledgeAssetVersion).where(KnowledgeAssetVersion.id == version_id)
            )
        ).scalar_one_or_none()
        if version is None or version.asset_id != asset.id:
            raise _denied(404, "version_not_found", "目标版本不存在或不属于该资产")
        if version.version_status != "active":
            raise _denied(403, "preview_type_not_available", "目标版本不可用")
        target_version_id = version.id

    # 生成一次性 token，仅保存其 sha256 哈希；指纹为哈希前 16 位（可对外）。
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    fingerprint = token_hash[:16]

    cred = PreviewCredential(
        target_asset_id=asset.id,
        target_version_id=target_version_id,
        requester_user_id=caller.user_id,
        preview_type=PreviewType.full.value,
        credential_status=CredentialStatus.active.value,
        token_hash=token_hash,
        credential_fingerprint=fingerprint,
        preview_entry_url="",  # 先占位，拿到 id 后回填
        issued_at=utc_now(),
        expires_at=utc_now() + timedelta(minutes=PREVIEW_TTL_MINUTES),
        trace_id=trace_id,
    )
    session.add(cred)
    await session.flush()
    cred.preview_entry_url = f"/api/v1/preview/{cred.id}"

    is_l5 = asset.confidentiality_level == ConfidentialityLevel.L5.value
    # 预览签发审计：只记 credential_fingerprint（不可逆指纹），不记完整 token / entry_url。
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.preview_issued.value,
        trace_id=trace_id,
        target_type="preview_credential",
        target_id=cred.id,
        after={
            "preview_type": cred.preview_type,
            "credential_fingerprint": cred.credential_fingerprint,
            "asset_id": str(asset.id),
            "confidentiality_level": asset.confidentiality_level,
        },
        project_id=asset.project_id,
    )
    if is_l5:
        # boss / 咨询总监对 L5 原文签发预览：强审计。
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.l5_original_access.value,
            trace_id=trace_id,
            target_type="preview_credential",
            target_id=cred.id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "credential_fingerprint": cred.credential_fingerprint,
                "asset_id": str(asset.id),
                "confidentiality_level": asset.confidentiality_level,
            },
            project_id=asset.project_id,
        )
    await session.commit()

    return PreviewIssueResponse(
        credential_id=cred.id,
        preview_type=cred.preview_type,
        credential_fingerprint=cred.credential_fingerprint,
        preview_entry_url=cred.preview_entry_url,
        expires_at=cred.expires_at,
        credential_status=cred.credential_status,
    )


async def use_preview_entry(
    session: AsyncSession,
    caller: CallerContext,
    credential_id: uuid.UUID,
    trace_id: str,
) -> PreviewEntryResponse:
    """平台受控占位预览入口：校验凭证 + 资产状态，更新使用时间，返回占位 metadata。"""
    if not caller.is_business_user:
        await audit_service.record_denied(
            session,
            caller=caller,
            log_type=AuditLogType.exception,
            action=AuditAction.admin_business_denied.value,
            trace_id=trace_id,
            target_type="preview_credential",
            target_id=credential_id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={"denied_reason": "admin_business_permission_denied", "attempted": "preview.use"},
        )
        raise _denied(403, "admin_business_permission_denied", "仅业务用户可使用预览入口")
    cred = (
        await session.execute(
            select(PreviewCredential).where(PreviewCredential.id == credential_id)
        )
    ).scalar_one_or_none()
    not_found = _denied(404, "preview_credential_not_found", "预览凭证不存在")
    if cred is None:
        raise not_found
    # 仅凭证申请人可使用（不泄露给他人）。
    if cred.requester_user_id != caller.user_id:
        raise not_found

    if cred.credential_status == CredentialStatus.revoked.value:
        raise _denied(403, "preview_credential_revoked", "预览凭证已撤销")
    if cred.credential_status == CredentialStatus.expired.value:
        raise _denied(403, "preview_credential_expired", "预览凭证已过期")

    # 过期检查：过期则置 expired 并拒绝。
    if _as_aware(cred.expires_at) <= utc_now():
        cred.credential_status = CredentialStatus.expired.value
        await session.commit()
        raise _denied(403, "preview_credential_expired", "预览凭证已过期")

    # 资产仍需 active：archived/deprecated 则撤销凭证并拒绝。
    asset = (
        await session.execute(
            select(KnowledgeAsset).where(KnowledgeAsset.id == cred.target_asset_id)
        )
    ).scalar_one_or_none()
    if asset is None or asset.asset_status in _INACTIVE_STATUSES:
        cred.credential_status = CredentialStatus.revoked.value
        cred.revoked_at = utc_now()
        await session.commit()
        raise _denied(403, "asset_not_active", "资产不可用，凭证已失效")

    now = utc_now()
    if cred.used_at is None:
        cred.used_at = now
    cred.last_used_at = now

    # 预览入口使用审计；L5 原文预览使用为强审计。
    await audit_service.record_event(
        session,
        caller=caller,
        log_type=AuditLogType.operation,
        action=AuditAction.preview_used.value,
        trace_id=trace_id,
        target_type="preview_credential",
        target_id=cred.id,
        extra={
            "credential_fingerprint": cred.credential_fingerprint,
            "asset_id": str(asset.id),
            "confidentiality_level": asset.confidentiality_level,
        },
        project_id=asset.project_id,
    )
    if asset.confidentiality_level == ConfidentialityLevel.L5.value:
        await audit_service.record_event(
            session,
            caller=caller,
            log_type=AuditLogType.operation,
            action=AuditAction.preview_l5_used.value,
            trace_id=trace_id,
            target_type="preview_credential",
            target_id=cred.id,
            severity=AlertSeverity.warning,
            risk_level=AuditRiskLevel.high.value,
            extra={
                "credential_fingerprint": cred.credential_fingerprint,
                "asset_id": str(asset.id),
                "confidentiality_level": asset.confidentiality_level,
            },
            project_id=asset.project_id,
        )
    # ---- 按文件类型分发渲染方式（D1 后 UX 修复：pdf/图片/md/文本轻量预览，
    # office 走 ONLYOFFICE 只读兜底）----
    original = await _resolve_original(session, asset.id)
    document_title = safe_filename(original[1]) if original else asset.title
    render_type: str | None = None
    file_url: str | None = None
    onlyoffice_config: dict | None = None
    message: str | None = None

    if original is None:
        message = "preview_source_unavailable"  # 无可用原文源（如未经入库的资产）
    else:
        render_type = _render_type_for(original[1])
        if render_type is None:
            message = "preview_type_not_available"  # 类型不支持
        elif render_type == "office":
            if not onlyoffice_enabled():
                render_type = None
                message = "onlyoffice_not_configured"  # 未配置：绝不回退泄露原文 URL
            else:
                # 铸造短时不透明取件 token：仅哈希入库（明文只进取件 URL）。
                fetch_token = secrets.token_urlsafe(32)
                cred.fetch_token_hash = _hash(fetch_token)
                file_url = f"/api/v1/preview/{cred.id}/file?ft={fetch_token}"
                base = (get_settings().onlyoffice_internal_base_url or "").rstrip("/")
                fetch_url = f"{base}{file_url}" if base else file_url
                # 文档 key：按版本派生（同版本稳定，安全，非 storage_ref / 非内部主键明文）。
                document_key = _hash(str(cred.target_version_id or cred.id))[:20]
                try:
                    onlyoffice_config = build_view_config(
                        document_key=document_key,
                        document_title=document_title,
                        file_name=original[1],
                        fetch_url=fetch_url,
                    )
                except OnlyOfficeError as exc:
                    render_type = None
                    onlyoffice_config = None
                    message = exc.code
        else:
            # pdf / image / markdown / text：浏览器直接受控取件（同源相对路径）。
            fetch_token = secrets.token_urlsafe(32)
            cred.fetch_token_hash = _hash(fetch_token)
            file_url = f"/api/v1/preview/{cred.id}/file?ft={fetch_token}"

    await session.commit()

    return PreviewEntryResponse(
        credential_id=cred.id,
        target_asset_id=cred.target_asset_id,
        preview_type=cred.preview_type,
        document_title=document_title,
        credential_fingerprint=cred.credential_fingerprint,
        expires_at=cred.expires_at,
        credential_status=cred.credential_status,
        render_type=render_type,
        file_url=file_url,
        onlyoffice_config=onlyoffice_config,
        message=message,
    )


async def serve_preview_file(
    session: AsyncSession,
    credential_id: uuid.UUID,
    fetch_token: str,
    *,
    storage: LocalFileStorage,
) -> tuple[bytes, str, str]:
    """ONLYOFFICE 受控取件端点：凭短时 fetch_token 取原文字节（供 Document Server 回取）。

    仅凭 fetch_token 授权（Document Server 无会话）——token 仅在持权请求人使用预览入口时
    铸造，admin 无从取得。返回 (bytes, media_type, safe_filename)。任何校验失败 → 403/404，
    不泄露 storage_ref / 内部路径。
    """
    cred = (
        await session.execute(
            select(PreviewCredential).where(PreviewCredential.id == credential_id)
        )
    ).scalar_one_or_none()
    not_found = _denied(404, "preview_credential_not_found", "预览凭证不存在")
    if cred is None:
        raise not_found
    # fetch_token 校验（哈希比对；未铸造则拒绝）。
    if not fetch_token or not cred.fetch_token_hash or _hash(fetch_token) != cred.fetch_token_hash:
        raise _denied(403, "preview_fetch_token_invalid", "取件令牌无效")
    # 凭证状态 + 过期复核。
    if cred.credential_status == CredentialStatus.revoked.value:
        raise _denied(403, "preview_credential_revoked", "预览凭证已撤销")
    if (
        cred.credential_status == CredentialStatus.expired.value
        or _as_aware(cred.expires_at) <= utc_now()
    ):
        raise _denied(403, "preview_credential_expired", "预览凭证已过期")

    # 资产仍需 active。
    asset = (
        await session.execute(
            select(KnowledgeAsset).where(KnowledgeAsset.id == cred.target_asset_id)
        )
    ).scalar_one_or_none()
    if asset is None or asset.asset_status in _INACTIVE_STATUSES:
        raise _denied(403, "asset_not_active", "资产不可用")

    original = await _resolve_original(session, asset.id)
    if original is None:
        raise _denied(404, "preview_source_unavailable", "无可用原文源")
    storage_ref, file_name, mime = original
    try:
        data = storage.resolve_path(storage_ref).read_bytes()
    except (OSError, ValueError):
        # 不回显 storage_ref / 真实路径。
        raise _denied(404, "preview_source_unavailable", "原文读取失败") from None
    return data, (mime or "application/octet-stream"), safe_filename(file_name)
