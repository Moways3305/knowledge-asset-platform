from __future__ import annotations

from sqlalchemy import func, select

from app.models.audit import AuditEvent
from app.models.directory_migration import DirectoryMigrationCandidate
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.review import ReviewTask, ValidationEvidence
from app.seed.dev_seed import KA_PROJECT_ALPHA_MATERIAL, USER_BOSS


def _headers():
    return {"X-Dev-User-Id": str(USER_BOSS)}


async def test_historical_directory_migration_only_writes_governance_fields(client, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA_MATERIAL)
    version = await db_session.get(KnowledgeAssetVersion, asset.current_version_id)
    version.directory_key = None
    version.directory_rule_version = None
    version.directory_confirmed_by = None
    version.naming_metadata = {
        "scope": "project",
        "directory_key": "project.deliverables",
        "category_primary": "交付成果",
    }
    immutable = {
        "zone": asset.zone,
        "status": asset.asset_status,
        "canonical_name": asset.canonical_name,
        "index_status": version.index_status,
        "weknora_doc_id": version.weknora_doc_id,
        "version_hash": version.version_hash,
    }
    before_reviews = int(await db_session.scalar(select(func.count()).select_from(ReviewTask)) or 0)
    before_evidence = int(
        await db_session.scalar(select(func.count()).select_from(ValidationEvidence)) or 0
    )
    await db_session.commit()

    workspace = await client.get("/api/v1/admin/directory-migration", headers=_headers())
    assert workspace.status_code == 200, workspace.text
    item = next(row for row in workspace.json()["items"] if row["status"] == "clear_match")
    assert item["status"] == "clear_match"

    confirmed = await client.post(
        "/api/v1/admin/directory-migration/confirm",
        headers=_headers(),
        json={"items": [{"candidate_id": item["id"]}]},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["migrated"] == 1
    db_session.expire_all()
    asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA_MATERIAL)
    version = await db_session.get(KnowledgeAssetVersion, asset.current_version_id)
    assert version.directory_key == "project.deliverables"
    assert version.directory_rule_version is not None
    assert version.directory_confirmed_by == USER_BOSS
    assert asset.zone == immutable["zone"]
    assert asset.asset_status == immutable["status"]
    assert asset.canonical_name == immutable["canonical_name"]
    assert version.index_status == immutable["index_status"]
    assert version.weknora_doc_id == immutable["weknora_doc_id"]
    assert version.version_hash == immutable["version_hash"]
    assert (
        int(await db_session.scalar(select(func.count()).select_from(ReviewTask)) or 0)
        == before_reviews
    )
    assert (
        int(await db_session.scalar(select(func.count()).select_from(ValidationEvidence)) or 0)
        == before_evidence
    )
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.action == "directory_migration.confirmed")
        )
        == 1
    )


async def test_low_confidence_candidate_requires_manual_directory(client, db_session):
    asset = await db_session.get(KnowledgeAsset, KA_PROJECT_ALPHA_MATERIAL)
    version = await db_session.get(KnowledgeAssetVersion, asset.current_version_id)
    version.directory_key = None
    version.naming_metadata = {
        "scope": "project",
        "category_primary": "战略方案",
    }
    await db_session.execute(
        DirectoryMigrationCandidate.__table__.delete().where(
            DirectoryMigrationCandidate.version_id == version.id
        )
    )
    await db_session.commit()
    workspace = (await client.get("/api/v1/admin/directory-migration", headers=_headers())).json()
    item = next(row for row in workspace["items"] if row["status"] == "manual_required")
    assert item["status"] == "manual_required"
    auto = await client.post(
        "/api/v1/admin/directory-migration/confirm",
        headers=_headers(),
        json={"items": [{"candidate_id": item["id"]}]},
    )
    assert auto.json()["skipped"] == 1
    manual = await client.post(
        "/api/v1/admin/directory-migration/confirm",
        headers=_headers(),
        json={"items": [{"candidate_id": item["id"], "directory_key": "project.deliverables"}]},
    )
    assert manual.json()["migrated"] == 1
