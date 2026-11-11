"""企业微信通知真实下发。

`notification_records` 仍是唯一事实源（in_app 本地可见）。本模块新增**可 fake 的 WeCom
发送器** + **派发器**：把 channel=wecom 的待发记录经企微应用消息接口真实下发。

强约束：
- 消息体只含**安全元数据**（title / content，已在落库时值级脱敏）——绝不含业务原文 /
  抽取全文 / 原始 chunk / 完整预览 token / storage_ref / provider 内部 id / 任何密钥 / 文件 URL。
- 收件人按 `users.wecom_user_id` 解析；缺失/非 active → 安全失败，不自动建人。
- 上游错误映射为安全 code（不存原始 payload）。发送失败**绝不**回滚底层治理事实。
- 通知下发不是授权：不授予任何访问、不携带原文。
"""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.identity import User
from app.models.lifecycle import NotificationRecord
from app.schemas.enums import (
    AuditAction,
    AuditLogType,
    NotificationChannel,
)
from app.services import audit as audit_service
from app.services import notification_delivery as delivery
from app.services.wecom_client import WeComError, wecom_enabled


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
        sending = False
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                tok = await client.get(
                    f"{self._base}/cgi-bin/gettoken",
                    params={"corpid": self._corp_id, "corpsecret": self._app_secret},
                )
                tok.raise_for_status()
                token = (tok.json() or {}).get("access_token")
                if not token:
                    raise WeComError("wecom_token_failed", "企微 access_token 获取失败")
                sending = True
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
                resp.raise_for_status()
                data = resp.json() or {}
        except httpx.HTTPError as exc:
            raise WeComError(
                "delivery_outcome_unknown" if sending else "wecom_network_error",
                f"企微网络错误（{type(exc).__name__}）",
            ) from exc
        errcode = data.get("errcode")
        if type(errcode) is not int:
            raise WeComError("delivery_outcome_unknown", "企微消息响应缺少结果码")
        if errcode != 0:
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
        base_url=s.wecom_api_base_url,
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
    result = await delivery.dispatch(
        session,
        policy=delivery.Policy(
            model=NotificationRecord,
            status="send_status",
            attempts="send_attempts",
            failure="failure_reason",
            delivered="sent_at",
            prepare=_prepare_delivery,
            audit=_audit_delivery,
        ),
        sender=sender,
        trace_id=trace_id,
        limit=limit,
    )
    result.pop("expired")
    return result


async def _prepare_delivery(session: AsyncSession, row: NotificationRecord):
    user = await session.get(User, row.recipient_user_id)
    if user is None or user.status != "active" or not user.wecom_user_id:
        return delivery.Failure("recipient_unavailable")
    return delivery.Message(user.wecom_user_id, row.title, row.content)


async def _audit_delivery(session, row, failed: bool, trace_id: str | None):
    await _audit(
        session,
        AuditAction.notification_failed.value if failed else AuditAction.notification_sent.value,
        row,
        trace_id,
    )


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
