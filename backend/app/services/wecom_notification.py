"""企业微信通知真实下发。

`notification_records` 仍是唯一事实源（in_app 本地可见）。本模块新增**可 fake 的 WeCom
发送器** + **派发器**：把 channel=wecom 的待发记录经企微应用消息接口真实下发。

强约束：
- 消息体只含**安全元数据**（title / content，已在落库时值级脱敏）——绝不含业务原文 /
  抽取全文 / 原始 chunk / 完整预览 token / storage_ref / WeKnora·Dify id / 任何密钥 / 文件 URL。
- 收件人按 `users.wecom_user_id` 解析；缺失/非 active → 安全失败，不自动建人。
- 上游错误映射为安全 code（不存原始 payload）。发送失败**绝不**回滚底层治理事实。
- 通知下发不是授权：不授予任何访问、不携带原文。
"""

from __future__ import annotations

import httpx
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.utils import utc_now
from app.models.identity import User
from app.models.lifecycle import NotificationRecord
from app.schemas.enums import (
    AuditAction,
    AuditLogType,
    NotificationChannel,
    NotificationStatus,
)
from app.services import audit as audit_service
from app.services.wecom_client import WeComError, wecom_enabled

# 重试上限：超过则不再下发（失败终态）。
MAX_SEND_ATTEMPTS = 3


def wecom_send_enabled() -> bool:
    """WeCom 真实下发总开关：必须 `WECOM_NOTIFY_ENABLED` 且企微已配置（fail closed）。"""
    return bool(get_settings().wecom_notify_enabled and wecom_enabled())


def default_notification_channel() -> str:
    """治理通知默认渠道：开启 WeCom 下发且企微已配置 → wecom，否则 in_app（本地）。"""
    if wecom_send_enabled():
        return NotificationChannel.wecom.value
    return NotificationChannel.in_app.value


class WeComNotificationSender:
    """企微应用消息发送器（真实 httpx）。失败抛安全 WeComError。"""

    def __init__(
        self, *, corp_id: str, agent_id: str, app_secret: str, base_url: str, timeout: float = 30.0
    ) -> None:
        self._corp_id = corp_id
        self._agent_id = agent_id
        self._app_secret = app_secret
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    async def send(
        self, *, wecom_user_id: str, title: str, content: str, trace_id: str | None = None
    ) -> None:  # pragma: no cover - 真实网络
        if not self._agent_id:
            raise WeComError("wecom_no_agent_id", "企微 agentid 未配置")
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                tok = await client.get(
                    f"{self._base}/cgi-bin/gettoken",
                    params={"corpid": self._corp_id, "corpsecret": self._app_secret},
                )
                token = (tok.json() or {}).get("access_token")
                if not token:
                    raise WeComError("wecom_token_failed", "企微 access_token 获取失败")
                resp = await client.post(
                    f"{self._base}/cgi-bin/message/send",
                    params={"access_token": token},
                    json={
                        "touser": wecom_user_id,
                        "msgtype": "text",
                        "agentid": int(self._agent_id)
                        if str(self._agent_id).isdigit()
                        else self._agent_id,
                        "text": {"content": f"{title}\n{content}"},
                    },
                )
                data = resp.json() or {}
        except httpx.HTTPError as exc:
            raise WeComError(
                "wecom_network_error", f"企微网络错误（{type(exc).__name__}）"
            ) from exc
        errcode = data.get("errcode", 0)
        if errcode and int(errcode) != 0:
            # 不回显上游 errmsg（可能含敏感串）。
            raise WeComError(f"wecom_msg_{int(errcode)}", "企微消息下发失败")


class NullWeComNotificationSender:
    async def send(self, **_) -> None:
        raise WeComError("wecom_not_configured", "企微通知未配置")


def get_wecom_notification_sender() -> WeComNotificationSender | NullWeComNotificationSender:
    """FastAPI / worker 依赖：**WECOM_NOTIFY_ENABLED 且企微配齐**才给真实发送器；否则 Null。

    特性开关 fail closed：默认关时 worker 拿到的是 Null 发送器，派发器据此不外发（见
    dispatch_pending 守卫）。测试可注入 fake 发送器绕过工厂。
    """
    if not wecom_send_enabled():
        return NullWeComNotificationSender()
    s = get_settings()
    return WeComNotificationSender(
        corp_id=s.wecom_corp_id,
        agent_id=s.wecom_agent_id,
        app_secret=s.wecom_app_secret,
        base_url=s.wecom_drive_base_url,
        timeout=s.wecom_timeout,
    )


async def dispatch_pending(
    session: AsyncSession,
    *,
    sender,
    trace_id: str | None = None,
    limit: int = 100,
) -> dict:
    """下发 channel=wecom 的待发 / 可重试通知。幂等：已 sent 不再处理。返回安全计数。

    特性开关 fail closed：发送器不可用（Null，即 WECOM_NOTIFY_ENABLED 关 / 未配置）时
    **不尝试任何外发**，记录保持 pending（开启后可继续派发），不误标失败、不漏发。
    """
    if isinstance(sender, NullWeComNotificationSender):
        return {"sent": 0, "failed": 0, "processed": 0, "skipped": "wecom_notify_disabled"}
    rows = list(
        (
            await session.execute(
                select(NotificationRecord)
                .where(NotificationRecord.channel == NotificationChannel.wecom.value)
                .where(
                    or_(
                        NotificationRecord.send_status == NotificationStatus.pending.value,
                        (NotificationRecord.send_status == NotificationStatus.failed.value)
                        & (NotificationRecord.send_attempts < MAX_SEND_ATTEMPTS),
                    )
                )
                .order_by(NotificationRecord.created_at)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    sent = failed = 0
    for rec in rows:
        rec.send_attempts = (rec.send_attempts or 0) + 1
        user = await session.get(User, rec.recipient_user_id)
        if user is None or user.status != "active" or not user.wecom_user_id:
            rec.send_status = NotificationStatus.failed.value
            rec.failure_reason = "recipient_unavailable"
            failed += 1
            await _audit(session, AuditAction.notification_failed.value, rec, trace_id)
            continue
        try:
            await sender.send(
                wecom_user_id=user.wecom_user_id,
                title=rec.title,
                content=rec.content,
                trace_id=trace_id,
            )
        except WeComError as exc:
            rec.send_status = NotificationStatus.failed.value
            rec.failure_reason = exc.code  # 安全 code，不存原始 payload
            failed += 1
            await _audit(session, AuditAction.notification_failed.value, rec, trace_id)
            continue
        rec.send_status = NotificationStatus.sent.value
        rec.sent_at = utc_now()
        rec.failure_reason = None
        sent += 1
        await _audit(session, AuditAction.notification_sent.value, rec, trace_id)
    await session.commit()
    return {"sent": sent, "failed": failed, "processed": len(rows)}


async def _audit(
    session: AsyncSession, action: str, rec: NotificationRecord, trace_id: str | None
) -> None:
    """系统下发审计：只记安全元数据（通知 id / 收件人 / 渠道 / 失败 code），不记 title/content。"""
    await audit_service.record_system_event(
        session,
        log_type=AuditLogType.operation,
        action=action,
        trace_id=trace_id or "",
        target_type="notification_record",
        target_id=rec.id,
        extra={
            "channel": rec.channel,
            "recipient_user_id": str(rec.recipient_user_id),
            "send_attempts": rec.send_attempts,
            "failure_reason": rec.failure_reason,
        },
    )
