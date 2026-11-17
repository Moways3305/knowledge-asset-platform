"""Whole-document/library coverage and cancellable, disposable run history."""

import json
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from test_maintenance_agent import Model, configure, content_asset, headers, run_asset

from app.db.utils import utc_now
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetChunk,
    KnowledgeAssetSummary,
    KnowledgeAssetVersion,
)
from app.models.maintenance_agent import MaintenanceIssue, MaintenanceRun, MaintenanceRunItem
from app.seed.dev_seed import USER_BOSS, USER_CONSULTANT
from app.services.maintenance_jobs import process_one

ROOT = "/api/v1/maintenance-agent/policies/company/runs"


class Segments(Model):
    def __init__(self):
        self.documents = []
        self.summaries = []

    async def chat_completion(self, messages, **kwargs):
        prompt = json.loads(messages[-1]["content"])
        self.documents.append(prompt["document"])
        self.summaries.append(prompt["summary"])
        return json.dumps(
            {
                "complete": True,
                "has_substantive_content": True,
                "sections_present": [],
                "findings": [],
            }
        )


async def finish(maker, model, storage):
    for _ in range(80):
        if not await process_one(maker, client=model, storage=storage):
            return
    pytest.fail("fixture failed to finish")


async def test_long_document_and_summary_are_fully_checked_in_bounded_windows(
    client, sessionmaker_fixture, tmp_path
):
    maker = sessionmaker_fixture
    await configure(client, content=True)
    body = "长文正文" * 7000 + "结尾独有内容"
    asset_id, storage = await content_asset(maker, tmp_path, body=body)
    async with maker() as session:
        asset = await session.get(KnowledgeAsset, asset_id)
        session.add(
            KnowledgeAssetSummary(
                asset_id=asset_id,
                version_id=asset.current_version_id,
                summary_type="detailed_summary",
                content="摘要" * 3000 + "摘要结尾",
            )
        )
        await session.commit()
    run_id = await run_asset(maker, asset_id)
    model = Segments()
    await finish(maker, model, storage)
    report = (await client.get(f"{ROOT}/{run_id}", headers=headers())).json()
    assert report["status"] == "completed", report
    assert len(model.documents) > 5
    assert all(len(text) <= 6000 for text in model.documents)
    assert all(len(text) <= 2500 for text in model.summaries)
    assert any("结尾独有内容" in text for text in model.documents)
    assert any("摘要结尾" in text for text in model.summaries)
    assert report["items"][0]["progress"]["body_checked"] == len(body)
    assert "work_state" not in report["items"][0]
    assert "body_limit" not in report["reasons"]
    async with maker() as session:
        assert not await session.scalar(
            select(MaintenanceIssue.id).where(
                MaintenanceIssue.asset_id == asset_id,
                MaintenanceIssue.rule.in_(["cover_only", "missing_content"]),
            )
        )


async def test_more_than_200_chunks_are_not_truncated(client, sessionmaker_fixture, tmp_path):
    maker = sessionmaker_fixture
    await configure(client, content=True)
    asset_id, storage = await content_asset(maker, tmp_path)
    async with maker() as session:
        asset = await session.get(KnowledgeAsset, asset_id)
        session.add_all(
            [
                KnowledgeAssetChunk(
                    asset_id=asset_id,
                    version_id=asset.current_version_id,
                    chunk_index=i,
                    chunk_type="text",
                    content_text=f"第{i}段独立正文",
                    chunk_status="active",
                )
                for i in range(1, 601)
            ]
        )
        await session.commit()
    await run_asset(maker, asset_id)
    model = Segments()
    await finish(maker, model, storage)
    assert any("第600段独立正文" in text for text in model.documents)


async def test_library_comparison_continues_past_first_500_candidates(
    client, sessionmaker_fixture, tmp_path
):
    maker = sessionmaker_fixture
    await configure(client, content=True)
    asset_id, storage = await content_asset(maker, tmp_path)
    async with maker() as session:
        for i in range(501):
            identity, version = uuid.UUID(int=2**128 - 1000 + i), uuid.uuid4()
            session.add(
                KnowledgeAsset(
                    id=identity,
                    title=f"批次候选-{i}",
                    scope="company",
                    zone="material",
                    asset_type="document",
                    owner_user_id=USER_BOSS,
                    maintainer_user_id=USER_BOSS,
                    confidentiality_level="L1",
                    ai_access_level="A1",
                    asset_status="active",
                    current_version_id=version,
                )
            )
            session.add(
                KnowledgeAssetVersion(
                    id=version,
                    asset_id=identity,
                    version_no="1",
                    version_status="active",
                    created_by=USER_BOSS,
                    file_hash="shared-content-hash" if i == 500 else str(i),
                )
            )
        await session.commit()
    run_id = await run_asset(maker, asset_id)
    await finish(maker, Segments(), storage)
    report = (await client.get(f"{ROOT}/{run_id}", headers=headers())).json()
    progress = report["items"][0]["progress"]
    assert progress["comparison_checked"] == progress["comparison_total"] > 500
    async with maker() as session:
        assert await session.scalar(
            select(MaintenanceIssue.id).where(
                MaintenanceIssue.asset_id == asset_id, MaintenanceIssue.related_asset_id == identity
            )
        )


async def test_cancel_and_delete_fence_late_model_result(client, sessionmaker_fixture, tmp_path):
    maker = sessionmaker_fixture
    await configure(client, content=True)
    asset_id, storage = await content_asset(maker, tmp_path)
    run_id = await run_asset(maker, asset_id)

    class CancelDuringCall(Model):
        async def chat_completion(self, *args, **kwargs):
            assert (
                await client.post(f"{ROOT}/{run_id}/cancel", headers=headers())
            ).status_code == 200
            assert (await client.delete(f"{ROOT}/{run_id}", headers=headers())).status_code == 200
            return '{"complete":true,"findings":[{"rule":"cover_only","quote":"目录第一章"}]}'

    await process_one(maker, client=CancelDuringCall(), storage=storage)
    async with maker() as session:
        assert await session.get(MaintenanceRun, run_id) is None
        assert (
            await session.scalar(
                select(MaintenanceIssue.id).where(MaintenanceIssue.asset_id == asset_id)
            )
            is None
        )
        assert await session.get(KnowledgeAsset, asset_id) is not None


async def test_record_deletion_is_atomic_authorized_and_preserves_issues(
    client, sessionmaker_fixture, tmp_path
):
    maker = sessionmaker_fixture
    await configure(client, content=True)
    asset_id, storage = await content_asset(maker, tmp_path)
    old = await run_asset(maker, asset_id)
    await finish(maker, Segments(), storage)
    active = await run_asset(maker, asset_id)
    async with maker() as session:
        issue_ids = set(await session.scalars(select(MaintenanceIssue.id)))
        assert issue_ids
    assert (
        await client.delete(f"{ROOT}/{old}", headers=headers(USER_CONSULTANT))
    ).status_code == 404
    assert (
        await client.post(
            f"{ROOT}/delete", headers=headers(), json={"run_ids": [str(old), str(active)]}
        )
    ).status_code == 409
    assert (await client.get(f"{ROOT}/{old}", headers=headers())).status_code == 200
    assert (await client.post(f"{ROOT}/{active}/cancel", headers=headers())).status_code == 200
    assert (
        await client.post(
            f"{ROOT}/delete", headers=headers(), json={"run_ids": [str(old), str(active)]}
        )
    ).json() == {"deleted_count": 2}
    async with maker() as session:
        assert set(await session.scalars(select(MaintenanceIssue.id))) == issue_ids
        assert await session.scalar(select(func.count()).select_from(MaintenanceRunItem)) == 0


async def test_retry_resumes_completed_prefix_after_model_failure(
    client, sessionmaker_fixture, tmp_path
):
    maker = sessionmaker_fixture
    await configure(client, content=True)
    asset_id, storage = await content_asset(maker, tmp_path, body="一" * 6000 + "二" * 7000)
    run_id = await run_asset(maker, asset_id)
    await process_one(maker, client=Segments(), storage=storage)

    class Timeout(Model):
        async def chat_completion(self, *args, **kwargs):
            raise TimeoutError("private provider details")

    for _ in range(3):
        async with maker() as session:
            run = await session.get(MaintenanceRun, run_id)
            run.lease_until = utc_now() - timedelta(seconds=1)
            await session.commit()
        await process_one(maker, client=Timeout(), storage=storage)
    await process_one(maker, client=Segments(), storage=storage)
    failed = (await client.get(f"{ROOT}/{run_id}", headers=headers())).json()
    assert failed["status"] == "partial"
    assert failed["reasons"] == {"model_timeout": 1}
    response = await client.post(f"{ROOT}/{run_id}/retry", headers=headers())
    assert response.status_code == 200, response.text
    model = Segments()
    await finish(maker, model, storage)
    assert all(text != "一" * 6000 for text in model.documents)
    retried = (await client.get(f"{ROOT}/{response.json()['id']}", headers=headers())).json()
    assert retried["status"] == "completed", retried
    assert (
        await client.post(f"{ROOT}/{response.json()['id']}/retry", headers=headers())
    ).status_code == 409
