"""Hourly personal summaries use the same leased delivery protocol as immediate sends."""

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.db.utils import utc_now
from app.models.notification import BusinessNotification as N
from app.models.notification import NotificationPreference
from app.schemas.notification_inbox import ChannelPreference


async def category_preferences(session, recipients, category):
    rows = list(
        await session.scalars(
            select(NotificationPreference).where(NotificationPreference.user_id.in_(recipients))
        )
    )
    return {
        row.user_id: ChannelPreference.model_validate(row.categories.get(category, {}))
        for row in rows
    }


def next_hour():
    return utc_now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


async def bundle_due(session):
    # Only outbox rows are locked; a concurrent dispatcher skips claimed members.
    # One transaction creates the envelope and assigns members, so a crash cannot
    # strand half a bundle. The envelope owns retry/lease/audit after commit.
    rows = list(
        await session.scalars(
            select(N)
            .where(N.channel == "digest_pending", N.delivery_available_at <= utc_now())
            .order_by(N.created_at, N.id)
            .limit(500)
            .with_for_update(skip_locked=True)
        )
    )
    groups = {}
    for row in rows:
        groups.setdefault((row.recipient_user_id, row.category), []).append(row)
    for (recipient, category), members in groups.items():
        digest_id = uuid.uuid4()
        session.add(
            N(
                id=digest_id,
                recipient_user_id=recipient,
                event_type="notification.digest",
                category=category,
                title="业务消息摘要",
                summary="查看平台通知中心了解进展。",
                target_kind="notification_digest",
                target_id=digest_id,
                dedup_key=f"notification.digest:{digest_id}",
                channel="wecom",
                in_app_enabled=False,
            )
        )
        for member in members:
            member.channel = "digest"
            member.delivery_digest_id = digest_id
    await session.commit()


async def prepare(session, envelope, caller, resolver, delivery):
    members = list(
        await session.scalars(
            select(N)
            .where(
                N.delivery_digest_id == envelope.id,
                N.recipient_user_id == envelope.recipient_user_id,
                N.read_at.is_(None),
                N.deleted_at.is_(None),
                N.archived_at.is_(None),
            )
            .order_by(N.created_at.desc())
        )
    )
    targets = {}
    for row in members:
        visible = await resolver(session, caller, row)
        if visible is not None:
            targets.setdefault((row.target_kind, row.target_id), visible)
    if not targets:
        return delivery.Failure("target_unavailable", terminal=True, expired=True)
    failed = sum(state.status in {"failed", "partial", "rejected"} for state in targets.values())
    pending = sum(state.action_required for state in targets.values())
    completed = sum(state.status == "completed" for state in targets.values())
    return f"本时段 {len(targets)} 项业务有更新：{completed} 项已完成，{failed} 项异常，{pending} 项需要处理。请进入平台通知中心查看详情。"
