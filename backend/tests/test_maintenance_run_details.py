"""Historical membership, empty runs, live visibility and unified-library coverage."""

import uuid

import pytest
from sqlalchemy import select, update
from test_maintenance_agent import configure, drain, headers, run_asset

from app.models.knowledge import KnowledgeAsset
from app.models.maintenance_agent import MaintenancePolicy, MaintenanceRun, MaintenanceRunItem
from app.seed.dev_seed import KA_COMPANY_L2, USER_ADMIN_ONLY, USER_CONSULTANT
from app.services.maintenance_jobs import start_run


def path(run_id, suffix=""):
    return f"/api/v1/maintenance-agent/policies/company/runs/{run_id}{suffix}"


async def test_material_records_are_targets_and_have_persistent_results(
    client, sessionmaker_fixture
):
    await configure(client)
    async with sessionmaker_fixture() as session:
        asset = await session.get(KnowledgeAsset, KA_COMPANY_L2)
        asset.zone = "material"
        await session.commit()
    run_id = await run_asset(sessionmaker_fixture)
    before = (await client.get(path(run_id), headers=headers())).json()
    assert before["target_count"] == 1
    assert before["items"][0]["status"] == "pending"
    await drain(sessionmaker_fixture)
    after = (await client.get(path(run_id), headers=headers())).json()
    assert after["historical_details_available"]
    assert after["items"][0]["status"] == "incomplete"
    assert after["items"][0]["coverage"]["quality"] == "content_not_authorized"
    assert after["items"][0]["findings"]
    assert "quote" not in str(after)
    second_id = await run_asset(sessionmaker_fixture)
    await drain(sessionmaker_fixture)
    assert second_id != run_id
    assert (await client.get(path(run_id), headers=headers())).json()["items"] == after["items"]


async def test_empty_run_finishes_without_worker_and_explains_inactive_records(
    client, sessionmaker_fixture
):
    await configure(client)
    async with sessionmaker_fixture() as session:
        await session.execute(
            update(KnowledgeAsset)
            .where(KnowledgeAsset.scope == "company")
            .values(asset_status="archived")
        )
        await session.commit()
    response = await client.post(
        "/api/v1/maintenance-agent/policies/company/runs", headers=headers()
    )
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "empty" and run["finished_at"]
    detail = (await client.get(path(run["id"]), headers=headers())).json()
    assert detail["scope_snapshot"]["excluded_counts"]["archived"] > 0
    assert detail["target_count"] == detail["total"] == 0


async def test_target_becomes_archived_is_recorded_as_skipped(client, sessionmaker_fixture):
    await configure(client)
    run_id = await run_asset(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        asset = await session.get(KnowledgeAsset, KA_COMPANY_L2)
        asset.asset_status = "archived"
        await session.commit()
    await drain(sessionmaker_fixture)
    detail = (await client.get(path(run_id, "?status=skipped"), headers=headers())).json()
    assert detail["target_count"] == detail["skipped_count"] == detail["total"] == 1
    assert detail["status"] == "partial"
    assert detail["items"][0]["reasons"] == ["asset_out_of_scope"]


async def test_target_membership_does_not_expand_while_run_is_queued(client, sessionmaker_fixture):
    await configure(client)
    async with sessionmaker_fixture() as session:
        asset = await session.get(KnowledgeAsset, KA_COMPANY_L2)
        asset.asset_status = "archived"
        policy = await session.scalar(select(MaintenancePolicy))
        run = await start_run(session, policy)
        run_id, count = run.id, run.target_count
        asset.asset_status = "active"
        await session.commit()
    await drain(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        ids = (
            await session.scalars(
                select(MaintenanceRunItem.asset_id).where(MaintenanceRunItem.run_id == run_id)
            )
        ).all()
        assert KA_COMPANY_L2 not in ids
        assert len(ids) == count


async def test_legacy_run_distinguishes_current_scope_from_history(client, sessionmaker_fixture):
    await configure(client)
    async with sessionmaker_fixture() as session:
        policy = await session.scalar(select(MaintenancePolicy))
        run = MaintenanceRun(
            policy_id=policy.id, policy_revision=policy.revision, kind="full", status="completed"
        )
        session.add(run)
        await session.commit()
        run_id = run.id
    body = (await client.get(path(run_id), headers=headers())).json()
    assert not body["historical_details_available"]
    assert body["scope_snapshot"] is None and body["settings"] is None
    assert body["current_scope"]["target_count"] > 0
    assert body["items"] == []


@pytest.mark.parametrize("user", [USER_ADMIN_ONLY, USER_CONSULTANT])
async def test_run_details_do_not_grant_library_management(client, sessionmaker_fixture, user):
    await configure(client)
    run_id = await run_asset(sessionmaker_fixture)
    assert (await client.get(path(run_id), headers=headers(user))).status_code == 404


async def test_live_scope_change_hides_title_and_id(client, sessionmaker_fixture):
    await configure(client)
    run_id = await run_asset(sessionmaker_fixture)
    await drain(sessionmaker_fixture)
    async with sessionmaker_fixture() as session:
        asset = await session.get(KnowledgeAsset, KA_COMPANY_L2)
        asset.scope = "personal"
        await session.commit()
    body = (await client.get(path(run_id), headers=headers())).json()
    assert body["items"] == [] and body["total"] == 0
    assert str(KA_COMPANY_L2) not in str(body)
    assert (await client.get(path(uuid.uuid4()), headers=headers())).status_code == 404


async def test_cancelled_run_does_not_leave_targets_waiting_forever(client, sessionmaker_fixture):
    policy = await configure(client)
    run_id = await run_asset(sessionmaker_fixture)
    response = await client.put(
        "/api/v1/maintenance-agent/policies/company",
        headers=headers(),
        json={"expected_revision": policy["revision"], "enabled": True},
    )
    assert response.status_code == 200
    body = (await client.get(path(run_id), headers=headers())).json()
    assert body["status"] == "cancelled" and body["skipped_count"] == 1
    assert body["items"][0]["status"] == "skipped"
    assert body["items"][0]["reasons"] == ["policy_changed"]
