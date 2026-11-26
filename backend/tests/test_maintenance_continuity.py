"""Exercise the reminder, replacement and recheck via the project manager's APIs."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from test_knowledge_review import state
from test_knowledge_versions import upload_update
from test_maintenance_agent import content_asset, headers
from test_maintenance_batches import Segments, finish
from test_personal_information_guard import EMAIL, PHONE

from app.db.utils import utc_now
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetChunk,
    KnowledgeAssetSummary,
    KnowledgeAssetVersion,
)
from app.models.maintenance_agent import MaintenancePolicy
from app.seed.dev_seed import PROJECT_ALPHA, USER_CONSULTANT, USER_PROJECT_MANAGER
from app.services import outbox
from app.services.maintenance_jobs import flush_digests, process_one, start_run

ROOT = "/api/v1/maintenance-agent"
KEY = f"project:{PROJECT_ALPHA}"
PM = headers(USER_PROJECT_MANAGER)


async def test_digest_membership_spans_libraries_and_rechecks_assignments(client, db_session):
    from test_maintenance_agent import configure

    from app.models.maintenance_agent import (
        MaintenanceDigest,
        MaintenanceDigestIssue,
        MaintenanceIssue,
    )
    from app.seed.dev_seed import KA_COMPANY_L2, KA_PROJECT_ALPHA

    company = await configure(client)
    project = (
        await client.put(
            f"{ROOT}/policies/{KEY}",
            headers=PM,
            json={"enabled": False, "content_authorized": False, "settings": {}},
        )
    ).json()
    original = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    original.maintainer_user_id, original.maintenance_delegated = USER_PROJECT_MANAGER, True
    # Assign project explicitly so that both libraries have the same recipient.
    asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA)
    asset.maintainer_user_id = USER_PROJECT_MANAGER
    digest = MaintenanceDigest(recipient_id=USER_PROJECT_MANAGER, day="2026-01-01")
    db_session.add(digest)
    for library, asset_id, rule, included in [
        (company, KA_COMPANY_L2, "parse_failed", True),
        (project, KA_PROJECT_ALPHA, "index_failed", True),
        (project, KA_PROJECT_ALPHA, "file_unavailable", False),
    ]:
        issue = MaintenanceIssue(
            policy_id=uuid.UUID(library["id"]),
            asset_id=asset_id,
            rule=rule,
            category="availability",
            fingerprint="test",
        )
        db_session.add(issue)
        await db_session.flush()
        if included:
            db_session.add(MaintenanceDigestIssue(digest_id=digest.id, issue_id=issue.id))
    await db_session.commit()
    url = f"{ROOT}/issues?digest_id={digest.id}"
    result = (await client.get(url, headers=PM)).json()
    assert set(result["digest_libraries"]) == {"company", KEY} and result["total"] == 2
    narrowed = (await client.get(url + "&library_key=" + KEY, headers=PM)).json()
    assert [i["rule"] for i in narrowed["items"]] == ["index_failed"]
    original.maintenance_delegated = False
    await db_session.commit()
    refreshed = (await client.get(url, headers=PM)).json()
    assert refreshed["digest_libraries"] == [KEY] and refreshed["total"] == 1


@pytest.mark.parametrize("successor_already_resolved", [False, True])
async def test_upgrade_recovers_proven_archive_closures_and_preserves_verified_successors(
    client, sessionmaker_fixture, tmp_path, successor_already_resolved
):
    import importlib.util
    from pathlib import Path

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from test_maintenance_agent import configure

    from app.models.maintenance_agent import (
        MaintenanceDigest,
        MaintenanceDigestIssue,
        MaintenanceIssue,
        MaintenanceIssueEvent,
    )
    from app.seed.dev_seed import USER_BOSS
    from app.services.maintenance_replacement import recover_archived_replacements

    maker = sessionmaker_fixture
    policy = await configure(client, content=True)
    source, _ = await content_asset(maker, tmp_path)
    target, _ = await content_asset(maker, tmp_path)
    async with maker() as session:
        old = await session.get(KnowledgeAsset, source)
        old.asset_status, old.archived_at, old.replacement_asset_id = "archived", utc_now(), target
        opts = dict(
            policy_id=uuid.UUID(policy["id"]),
            rule="personal_information",
            category="privacy",
            fingerprint="historical",
        )
        retired = MaintenanceIssue(asset_id=source, status="not_applicable", **opts)
        ordinary = MaintenanceIssue(
            asset_id=source, status="not_applicable", **{**opts, "rule": "parse_failed"}
        )
        notice = MaintenanceDigest(recipient_id=USER_BOSS, day="2026-01-02")
        session.add_all([retired, ordinary, notice])
        await session.flush()
        session.add_all(
            [
                MaintenanceIssueEvent(issue_id=retired.id, action="fact_reconciled"),
                MaintenanceIssueEvent(issue_id=ordinary.id, action="not_applicable"),
                MaintenanceDigestIssue(digest_id=notice.id, issue_id=retired.id),
            ]
        )
        if successor_already_resolved:
            verified = MaintenanceIssue(asset_id=target, status="resolved", **opts)
            session.add(verified)
            await session.flush()
            session.add(MaintenanceIssueEvent(issue_id=verified.id, action="recheck_passed"))
        await session.commit()
        path = (
            Path(__file__).resolve().parents[1] / "alembic/versions/0094_maintenance_continuity.py"
        )
        spec = importlib.util.spec_from_file_location("migration94", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        def cycle(conn):
            migration.op = Operations(MigrationContext.configure(conn))
            migration.downgrade()
            migration.upgrade()

        await (await session.connection()).run_sync(cycle)
        await session.commit()
        notice_id, old_issue_id = notice.id, retired.id
        session.expire_all()
        await recover_archived_replacements(session)
        await recover_archived_replacements(session)
    listing = (
        await client.get(f"{ROOT}/issues?digest_id={notice_id}&status=all", headers=headers())
    ).json()
    (linked,) = listing["items"]
    assert linked["asset_id"] == str(target)
    assert linked["status"] == ("resolved" if successor_already_resolved else "awaiting_recheck")
    assert (await client.get(f"{ROOT}/issues/{old_issue_id}", headers=headers())).json()[
        "id"
    ] == linked["id"]


async def scan(maker, asset_id, storage):
    async with maker() as session:
        policy = await session.scalar(
            select(MaintenancePolicy).where(MaintenancePolicy.library_key == KEY)
        )
        await start_run(session, policy, asset_id=asset_id)
        await session.commit()
    await finish(maker, Segments(), storage)


async def reminder(client, maker):
    async with maker() as session:
        await flush_digests(session, utc_now() + timedelta(days=1))
        await outbox.process_pending(session, limit=100)
    inbox = await client.get("/api/v1/notifications/inbox", headers=PM)
    assert PHONE not in inbox.text and EMAIL not in inbox.text
    (group,) = [
        g
        for g in inbox.json()["items"]
        if g["latest"]["target"]["route_key"] == "maintenance_agent"
    ]
    events = await client.get(
        "/api/v1/notifications/inbox/events",
        headers=PM,
        params={"group_id": group["id"], "snapshot_at": inbox.json()["snapshot_at"]},
    )
    (row,) = events.json()["items"]
    return row


@pytest.mark.parametrize("prescanned", [False, True])
async def test_project_reminder_survives_partial_repair_and_closes_only_after_recheck(
    client, sessionmaker_fixture, tmp_path, prescanned
):
    await project_version_workflow(client, sessionmaker_fixture, tmp_path, prescanned)


async def project_version_workflow(client, maker, tmp_path, prescanned):
    policy = await client.put(
        f"{ROOT}/policies/{KEY}",
        headers=PM,
        json={"enabled": False, "content_authorized": True, "settings": {}},
    )
    assert policy.status_code == 200, policy.text
    old_id, storage = await content_asset(maker, tmp_path, body=f"联系邮箱 {EMAIL}")
    async with maker() as session:
        old = await session.get(KnowledgeAsset, old_id)
        old.scope, old.project_id = "project", PROJECT_ALPHA
        old.owner_user_id = old.maintainer_user_id = USER_PROJECT_MANAGER
        version = await session.get(KnowledgeAssetVersion, old.current_version_id)
        version.directory_key = "project.deliverables"
        version.version_no = "V1"
        session.add(
            KnowledgeAssetSummary(
                asset_id=old_id,
                version_id=version.id,
                summary_type="detailed",
                content=f"电话 {PHONE}",
            )
        )
        await session.commit()
    await scan(maker, old_id, storage)
    notice = await reminder(client, maker)
    assert notice["action_required"]
    digest_id = notice["target"]["resource_id"]
    url = f"{ROOT}/issues?digest_id={digest_id}&category=privacy"
    result = await client.get(url, headers=PM)
    assert result.status_code == 200, result.text
    assert result.json()["digest_libraries"] == [KEY]
    (issue,) = result.json()["items"]
    issue_url = f"{ROOT}/issues/{issue['id']}"
    assert (await client.get(url, headers=headers(USER_CONSULTANT))).status_code == 404
    original = (await client.get(issue_url, headers=PM)).json()
    assert set(original["evidence"]["counts"]) == {"email", "phone"}

    uploaded = await upload_update(client, old, USER_PROJECT_MANAGER)
    assert uploaded.status_code == 200, uploaded.text
    task_id = uploaded.json()["ingest_task_id"]
    confirmed = await client.post(
        f"/api/v1/ingest/{task_id}/confirm",
        headers=PM,
        json={
            "title": "修订后的参考资料",
            "summary": f"电话 {PHONE}",
            "target_scope": "project",
            "target_project_id": str(PROJECT_ALPHA),
            "target_zone": old.zone,
            "confidentiality_level": old.confidentiality_level,
            "directory_key": "project.deliverables",
        },
    )
    assert confirmed.status_code == 200, confirmed.text
    new_id = uuid.UUID(confirmed.json()["result_asset_id"])
    # Stand in only for the external indexer's completion callback.
    async with maker() as session:
        new = await session.get(KnowledgeAsset, new_id)
        version = await session.get(KnowledgeAssetVersion, new.current_version_id)
        version.weknora_parse_status, version.index_status = "completed", "indexed"
        if not await session.scalar(
            select(KnowledgeAssetChunk.id).where(KnowledgeAssetChunk.version_id == version.id)
        ):
            session.add(
                KnowledgeAssetChunk(
                    asset_id=new_id,
                    version_id=version.id,
                    chunk_index=0,
                    chunk_type="text",
                    content_text="新版实施方法与复盘 V2",
                    chunk_status="active",
                )
            )
        await session.commit()
    if prescanned:
        await scan(maker, new_id, client._kap_storage)
        (duplicate,) = (
            await client.get(f"{ROOT}/issues?asset_id={new_id}&category=privacy", headers=PM)
        ).json()["items"]
        queued_before_adoption = await client.post(
            f"{ROOT}/issues/{duplicate['id']}/actions",
            headers=PM,
            json={
                "action": "recheck",
                "expected_updated_at": duplicate["updated_at"],
                "reason": "",
            },
        )
        assert queued_before_adoption.status_code == 200

    adopted = await client.post(
        f"/api/v1/knowledge/{old_id}/trust/replacement",
        headers=PM,
        json={
            "expected_updated_at": (await state(client, old_id, USER_PROJECT_MANAGER))[
                "updated_at"
            ],
            "expected_replacement_updated_at": (await state(client, new_id, USER_PROJECT_MANAGER))[
                "updated_at"
            ],
            "replacement_asset_id": str(new_id),
            "confirm_archive": True,
            "reason": "采纳修订稿",
        },
    )
    assert adopted.status_code == 200, adopted.text
    (continued,) = (await client.get(url, headers=PM)).json()["items"]
    assert (continued["id"], continued["asset_id"], continued["status"]) == (
        issue["id"],
        str(new_id),
        "awaiting_recheck",
    )
    pending = (await client.get(issue_url, headers=PM)).json()
    assert pending["evidence"] == {} and pending["requires_recheck"]
    if prescanned:
        alias = await client.get(f"{ROOT}/issues/{duplicate['id']}", headers=PM)
        assert alias.json()["id"] == issue["id"]
        assert await process_one(maker, client=Segments(), storage=client._kap_storage)
        unchanged = (await client.get(issue_url, headers=PM)).json()
        assert unchanged["status"] == "awaiting_recheck" and not unchanged["evidence_available"]

    await finish(maker, Segments(), client._kap_storage)
    partial = await client.get(issue_url, headers=PM)
    assert partial.json()["status"] == "open" and set(partial.json()["evidence"]["counts"]) == {
        "phone"
    }
    assert EMAIL not in partial.text and PHONE not in partial.text
    refused = await client.post(
        issue_url + "/actions",
        headers=PM,
        json={
            "expected_updated_at": partial.json()["updated_at"],
            "action": "resolved",
            "reason": "尚未复检通过",
        },
    )
    assert refused.status_code == 409
    fixed = await client.patch(
        f"/api/v1/knowledge/{new_id}/metadata",
        headers=PM,
        json={
            "summary": "已修订联系方式。",
            "reason": "移除测试值",
            "expected_updated_at": (await state(client, new_id, USER_PROJECT_MANAGER))[
                "updated_at"
            ],
        },
    )
    assert fixed.status_code == 200, fixed.text
    current = (await client.get(issue_url, headers=PM)).json()
    assert current["status"] == "open"
    # A failed/incomplete body check cannot certify the repair.
    async with maker() as session:
        ver = await session.get(KnowledgeAssetVersion, new.current_version_id)
        ver.weknora_parse_status = "processing"
        await session.commit()
    for expected in ("open", "resolved"):
        current = (await client.get(issue_url, headers=PM)).json()
        queued = await client.post(
            issue_url + "/actions",
            headers=PM,
            json={
                "expected_updated_at": current["updated_at"],
                "action": "recheck",
                "reason": "",
            },
        )
        assert queued.status_code == 200, queued.text
        await finish(maker, Segments(), client._kap_storage)
        checked = (await client.get(issue_url, headers=PM)).json()
        assert checked["status"] == expected
        if expected == "open":
            async with maker() as session:
                ver = await session.get(KnowledgeAssetVersion, new.current_version_id)
                ver.weknora_parse_status = "completed"
                await session.commit()
    actions = [entry["action"] for entry in checked["history"]]
    assert {"detected", "version_replaced", "recheck_incomplete", "recheck_passed"} <= set(actions)
    assert not checked["requires_recheck"]
    await scan(maker, new_id, client._kap_storage)
    assert (await client.get(url, headers=PM)).json()["total"] == 0
    (historical,) = (await client.get(url + "&status=all", headers=PM)).json()["items"]
    assert historical["id"] == issue["id"] and historical["status"] == "resolved"
    final = await reminder(client, maker)
    assert final["id"] == notice["id"] and final["task_status"] == "completed"
