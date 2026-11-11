"""Synthetic original-access scan rehearsal; only compose.capacity-test resources."""

import argparse
import asyncio
import time
import uuid
from datetime import timedelta

from capacity_common import DATABASE, guard
from capacity_probe import save
from sqlalchemy import event, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

guard()

from app.db.utils import utc_now  # noqa: E402
from app.models.audit import AuditEvent  # noqa: E402
from app.models.identity import User  # noqa: E402
from app.models.knowledge import KnowledgeAsset  # noqa: E402
from app.models.original_access import AccessGrant, OriginalAccessRequest  # noqa: E402
from app.models.outbox import DomainEventOutbox  # noqa: E402
from app.models.permission_rule import PermissionRule  # noqa: E402
from app.services import original_access, permission_rules  # noqa: E402

PREFIX = "capacity-access-"


async def seed(maker, blocked=100, eligible=20):
    async with maker() as session:
        users = list(await session.scalars(select(User)))
        assert len(users) == 100 and all(u.email.endswith("@example.invalid") for u in users)
        requester = next(u for u in users if u.email == "capacity-0@example.invalid")
        owner = next(u for u in users if u.email == "capacity-99@example.invalid")
        await permission_rules.ensure_default_rules(session)
        for key, values in {
            "access_request_timeout_hours": {"enabled": True, "value_number": 1},
            "company_l1_l2_original_for_business_user": {"enabled": True, "value_bool": False},
        }.items():
            await session.execute(
                update(PermissionRule).where(PermissionRule.rule_key == key).values(**values)
            )
        # Isolate cohorts without deleting audit/grant history.
        await session.execute(
            update(OriginalAccessRequest)
            .where(
                OriginalAccessRequest.asset_id.in_(
                    select(KnowledgeAsset.id).where(KnowledgeAsset.title.startswith(PREFIX))
                ),
                OriginalAccessRequest.status == "pending",
            )
            .values(status="cancelled")
        )
        now = utc_now()
        requests = []
        for index in range(blocked + eligible):
            asset = KnowledgeAsset(
                id=uuid.uuid4(),
                title=f"{PREFIX}{index}",
                scope="company",
                zone="asset",
                asset_type="document",
                owner_user_id=owner.id,
                visibility="company",
                confidentiality_level="L3" if index < blocked else "L2",
                ai_access_level="A1",
                asset_status="active",
                created_at=now - timedelta(days=5),
                updated_at=now - timedelta(days=3),
                verified_updated_at=now - timedelta(days=3),
            )
            session.add(asset)
            await session.flush()
            req = OriginalAccessRequest(
                id=uuid.uuid4(),
                asset_id=asset.id,
                requester_user_id=requester.id,
                status="pending",
                created_at=now - timedelta(hours=5) + timedelta(seconds=index),
            )
            session.add(req)
            requests.append(req)
        await session.commit()
        return [r.id for r in requests], [r.asset_id for r in requests]


async def facts(maker, ids, assets):
    async with maker() as session:
        statuses = dict(
            (
                await session.execute(
                    select(OriginalAccessRequest.status, func.count())
                    .where(OriginalAccessRequest.id.in_(ids))
                    .group_by(OriginalAccessRequest.status)
                )
            ).all()
        )
        grants = await session.scalar(
            select(func.count()).select_from(AccessGrant).where(AccessGrant.asset_id.in_(assets))
        )
        events = await session.scalar(
            select(func.count())
            .select_from(DomainEventOutbox)
            .where(DomainEventOutbox.aggregate_id.in_(ids))
        )
        audits = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.target_id.in_(
                    select(AccessGrant.id).where(AccessGrant.asset_id.in_(assets))
                ),
                AuditEvent.action == "access.original_approved",
            )
        )
        unchanged = await session.scalar(
            select(func.count())
            .select_from(KnowledgeAsset)
            .where(
                KnowledgeAsset.id.in_(assets),
                KnowledgeAsset.asset_status == "active",
                KnowledgeAsset.updated_at == KnowledgeAsset.verified_updated_at,
            )
        )
        confidential_grants = await session.scalar(
            select(func.count())
            .select_from(AccessGrant)
            .join(KnowledgeAsset, AccessGrant.asset_id == KnowledgeAsset.id)
            .where(AccessGrant.asset_id.in_(assets), KnowledgeAsset.confidentiality_level != "L2")
        )
        return {
            "request_statuses": statuses,
            "grants": grants,
            "audits": audits,
            "outbox": events,
            "business_assets_unchanged": unchanged,
            "confidential_grants": confidential_grants,
        }


async def no_wakeup(_session):
    pass


async def main(args):
    original_access.enqueue_outbox_delivery = no_wakeup
    engine = create_async_engine(DATABASE)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    transactions, beginnings = [], {}

    def begin(conn):
        beginnings[id(conn)] = time.monotonic()

    def end(conn):
        start = beginnings.pop(id(conn), None)
        if start is not None:
            transactions.append(time.monotonic() - start)

    try:
        ids, assets = await seed(maker)
        for name, fn in [("begin", begin), ("commit", end), ("rollback", end)]:
            event.listen(engine.sync_engine, name, fn)
        started, scans = time.monotonic(), []
        for n in range(100):
            async with maker() as session:
                kwargs = {"resume_only": n > 0} if args.phase == "fixed" else {}
                scans.append(
                    await original_access.auto_approve_timed_out_original_access_requests(
                        session, trace_id="synthetic-access", **kwargs
                    )
                )
            if args.phase == "baseline":
                if n == 2:
                    break
            else:
                async with maker() as session:
                    if not await session.scalar(
                        text(
                            "SELECT completed_at IS NULL FROM governance_scan_runs WHERE name='original_access'"
                        )
                    ):
                        break
        else:
            raise AssertionError("scan did not finish")
        result = await facts(maker, ids, assets)
        expected = 20 if args.phase == "fixed" else 0
        assert result["grants"] == result["audits"] == result["outbox"] == expected, result
        assert result["confidential_grants"] == 0 and result["business_assets_unchanged"] == 120
        save(
            f"access-{args.phase}",
            {
                "phase": args.phase,
                "synthetic_only": True,
                "production_changed": False,
                "skippable_prefix": 100,
                "eligible_tail": 20,
                "seconds": round(time.monotonic() - started, 3),
                "max_transaction_seconds": round(max(transactions, default=0), 4),
                "scans": scans,
                **result,
            },
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["baseline", "fixed"], required=True)
    asyncio.run(main(parser.parse_args()))
