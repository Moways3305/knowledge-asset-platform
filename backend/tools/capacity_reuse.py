"""Synthetic reuse scan baseline/batch measurements in compose.capacity-test only."""

import argparse
import asyncio
import json
import resource
import time
import uuid
from datetime import timedelta

from capacity_common import DATABASE, guard
from sqlalchemy import event, func, insert, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

guard()

from app.db.utils import utc_now  # noqa: E402
from app.models.agent import (  # noqa: E402
    AgentCall,
    AgentCallCitation,
    AgentGatewayDecision,
    AgentGatewayDecisionItem,
)
from app.models.audit import AuditEvent  # noqa: E402
from app.models.identity import Project, User, UserCompanyRole  # noqa: E402
from app.models.knowledge import KnowledgeAsset  # noqa: E402
from app.models.outbox import DomainEventOutbox  # noqa: E402
from app.services.jobs import reuse_upgrade  # noqa: E402

PREFIX = "capacity-reuse-"


async def no_wakeup(_session):
    pass


async def seed(maker, count, *, usage_current=False):
    async with maker() as session:
        users = list(await session.scalars(select(User)))
        assert len(users) == 100 and all(u.email.endswith("@example.invalid") for u in users)
        owner = next(u for u in users if u.email == "capacity-99@example.invalid")
        if not await session.scalar(
            select(UserCompanyRole.id).where(UserCompanyRole.company_role == "boss")
        ):
            session.add(UserCompanyRole(user_id=owner.id, company_role="boss", status="active"))
        # Keep old citations as realistic history, but suppress old recommendations.
        await session.execute(
            update(KnowledgeAsset)
            .where(KnowledgeAsset.title.startswith(PREFIX))
            .values(asset_status="archived")
        )
        project = Project(id=uuid.uuid4(), name="Synthetic reuse project")
        session.add(project)
        await session.flush()
        now = utc_now()
        stamp = now - timedelta(days=1)
        ids = sorted(uuid.uuid4() for _ in range(count))
        await session.execute(
            insert(KnowledgeAsset),
            [
                dict(
                    id=i,
                    title=f"{PREFIX}{count}-{n}",
                    scope="project",
                    zone="asset",
                    project_id=project.id,
                    owner_user_id=owner.id,
                    asset_type="document",
                    visibility="project",
                    confidentiality_level="L2",
                    ai_access_level="A1",
                    asset_status="active",
                    created_at=now - timedelta(days=10),
                    updated_at=now - timedelta(days=5),
                    verified_updated_at=now - timedelta(days=5),
                    last_called_at=stamp if usage_current else None,
                )
                for n, i in enumerate(ids)
            ],
        )
        calls, decisions, items, citations = [], [], [], []
        for asset_id in ids:
            for n in range(3):
                call_id, decision_id, item_id = (uuid.uuid4() for _ in range(3))
                calls.append(
                    dict(
                        id=call_id,
                        caller_user_id=owner.id,
                        project_id=project.id,
                        query_text="synthetic",
                        model_key="synthetic",
                        provider="weknora_llm",
                        capability="qa",
                        call_status="allowed",
                        created_at=stamp,
                    )
                )
                decisions.append(
                    dict(
                        id=decision_id,
                        call_id=call_id,
                        caller_user_id=owner.id,
                        decision_status="allowed",
                    )
                )
                items.append(
                    dict(
                        id=item_id,
                        decision_id=decision_id,
                        call_id=call_id,
                        caller_user_id=owner.id,
                        target_asset_id=asset_id,
                        target_scope="project",
                        target_confidentiality_level="L2",
                        target_ai_access_level="A1",
                        returned_layer="original",
                    )
                )
                citations.append(
                    dict(
                        id=uuid.uuid4(),
                        call_id=call_id,
                        decision_item_id=item_id,
                        cited_asset_id=asset_id,
                        used_access_layer="original",
                        cited_zone="asset",
                        citation_order=n + 1,
                        created_at=stamp,
                    )
                )
        for model, rows in (
            (AgentCall, calls),
            (AgentGatewayDecision, decisions),
            (AgentGatewayDecisionItem, items),
            (AgentCallCitation, citations),
        ):
            await session.execute(insert(model), rows)
        await session.commit()
        return ids


async def facts(maker, ids):
    async with maker() as session:
        audits = await session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(
                AuditEvent.target_id.in_(ids), AuditEvent.action == "knowledge.upgrade_recommended"
            )
        )
        events = await session.scalar(
            select(func.count())
            .select_from(DomainEventOutbox)
            .where(DomainEventOutbox.aggregate_id.in_(ids))
        )
        unchanged = await session.scalar(
            select(func.count())
            .select_from(KnowledgeAsset)
            .where(
                KnowledgeAsset.id.in_(ids),
                KnowledgeAsset.scope == "project",
                KnowledgeAsset.asset_status == "active",
                KnowledgeAsset.updated_at == KnowledgeAsset.verified_updated_at,
                KnowledgeAsset.last_called_at.is_not(None),
            )
        )
        return {"recommendations": audits, "outbox": events, "unchanged_with_usage": unchanged}


async def measure(maker, engine, phase):
    statements, aggregates, transactions, beginnings = [], [], [], {}

    def sql(_conn, _cursor, statement, _params, _context, _many):
        statements.append(1)
        if "GROUP BY agent_call_citations.cited_asset_id" in statement:
            aggregates.append("agent_call_citations.cited_asset_id IN" in statement)

    def begin(conn):
        beginnings[id(conn)] = time.monotonic()

    def end(conn):
        stamp = beginnings.pop(id(conn), None)
        if stamp is not None:
            transactions.append(time.monotonic() - stamp)

    listeners = [
        ("before_cursor_execute", sql),
        ("begin", begin),
        ("commit", end),
        ("rollback", end),
    ]
    for name, fn in listeners:
        event.listen(engine.sync_engine, name, fn)
    started, batches = time.monotonic(), 0
    try:
        while True:
            async with maker() as session:
                kwargs = {"resume_only": batches > 0} if phase == "fixed" else {}
                await reuse_upgrade.scan_reuse_and_recommend(session, **kwargs)
            batches += 1
            if phase == "baseline":
                break
            async with maker() as session:
                pending = await session.scalar(
                    text("SELECT completed_at IS NULL FROM governance_scan_runs WHERE name='reuse'")
                )
            if not pending:
                break
            assert batches < 1000
    finally:
        for name, fn in listeners:
            event.remove(engine.sync_engine, name, fn)
    return {
        "seconds": round(time.monotonic() - started, 3),
        "statements": len(statements),
        "aggregate_queries": len(aggregates),
        "all_aggregates_bounded": all(aggregates),
        "max_transaction_seconds": round(max(transactions, default=0), 4),
        "batches": batches,
        "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
    }


async def main(args):
    assert all(1 <= n <= 5000 for n in args.counts)
    reuse_upgrade.enqueue_outbox_delivery = no_wakeup
    engine = create_async_engine(DATABASE)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    results = []
    try:
        for count in args.counts:
            ids = await seed(maker, count)
            result = {
                "assets": count,
                "phase": args.phase,
                **await measure(maker, engine, args.phase),
                **await facts(maker, ids),
            }
            assert (
                result["recommendations"]
                == result["outbox"]
                == result["unchanged_with_usage"]
                == count
            )
            results.append(result)
            print(json.dumps(result), flush=True)
        with open(f"/capacity/reuse-{args.phase}.json", "w") as output:
            json.dump(
                {"synthetic_only": True, "production_changed": False, "results": results},
                output,
                indent=2,
            )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=["baseline", "fixed"], required=True)
    parser.add_argument("--counts", type=int, nargs="+", default=[100, 500, 1500])
    asyncio.run(main(parser.parse_args()))
