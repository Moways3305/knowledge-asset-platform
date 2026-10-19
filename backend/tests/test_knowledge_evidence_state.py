import json
import uuid
from types import SimpleNamespace

import pytest

from app.db.utils import utc_now
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.schemas.permission import AccessChannel, CallerContext
from app.seed.dev_seed import KA_COMPANY_L2, PROJECT_ALPHA, USER_CONSULTANT
from app.services.knowledge_evidence_state import attach_platform_state
from app.services.retrieval import Evidence


async def _fixture(session, *, relation=None, source_status="archived", cross_library=False):
    target = await session.get(KnowledgeAsset, KA_COMPANY_L2)
    version = await session.get(KnowledgeAssetVersion, target.current_version_id)
    version.version_no = "V2"
    now = utc_now()
    target.updated_at = target.verified_at = target.verified_updated_at = now
    source = KnowledgeAsset(
        id=uuid.uuid4(),
        title="PRIVATE_SOURCE_TITLE",
        scope="project" if cross_library else "company",
        project_id=PROJECT_ALPHA if cross_library else None,
        zone="material",
        asset_type="document",
        owner_user_id=USER_CONSULTANT,
        confidentiality_level="L2",
        ai_access_level="A1",
        asset_status=source_status,
        replacement_asset_id=target.id if relation == "accepted" else None,
    )
    session.add(source)
    if relation == "pending":
        session.add(
            IngestTask(
                source="local",
                source_file_ref="PRIVATE_STORAGE",
                source_file_name="PRIVATE_NAME",
                status="confirmed",
                result_asset_id=target.id,
                update_of_asset_id=source.id,
                created_by=USER_CONSULTANT,
            )
        )
    await session.commit()
    caller = CallerContext(
        user_id=USER_CONSULTANT,
        is_active=True,
        active_company_roles={"consultant"},
        active_project_ids=set(),
    )
    recalled = [SimpleNamespace(asset=target, version=version)]
    evidence = [
        Evidence(
            asset=target,
            used_layer="original",
            snippet="采用前旧版仍有效。",
            seq=None,
            weknora_chunk_ref="PRIVATE_CHUNK",
        )
    ]
    return caller, recalled, evidence, source


@pytest.mark.parametrize(
    "relation,expected", [(None, "unknown"), ("pending", "pending"), ("accepted", "adopted")]
)
async def test_platform_state_distinguishes_verification_from_confirmed_adoption(
    db_session, relation, expected
):
    caller, recalled, evidence, _ = await _fixture(db_session, relation=relation)
    await attach_platform_state(db_session, caller, evidence, recalled, channel=AccessChannel.agent)
    assert evidence[0].platform_state == {
        "version": "V2",
        "version_selection": "current",
        "asset_status": "active",
        "review_status": "verified",
        "adoption_status": expected,
    }
    assert "PRIVATE" not in json.dumps(evidence[0].platform_state)
    assert not db_session.dirty


@pytest.mark.parametrize(
    "case", ["active_source", "deleted_source", "cross_library", "ceiling", "noncurrent", "legacy"]
)
async def test_relationship_flags_respect_visibility_ceiling_and_current_version(db_session, case):
    caller, recalled, evidence, source = await _fixture(
        db_session,
        relation="accepted",
        source_status="active" if case == "active_source" else "archived",
        cross_library=case == "cross_library",
    )
    if case == "deleted_source":
        source.deleted_at = utc_now()
    if case == "noncurrent":
        recalled[0].asset.current_version_id = uuid.uuid4()
    if case == "legacy":
        recalled[0].asset.current_version_id = None
    await db_session.commit()
    await attach_platform_state(
        db_session,
        caller,
        evidence,
        recalled,
        channel=AccessChannel.agent,
        asset_guard=(lambda asset: asset.id != source.id) if case == "ceiling" else None,
    )
    assert evidence[0].platform_state["adoption_status"] == "unknown"
    assert "PRIVATE" not in json.dumps(evidence[0].platform_state)


async def test_withdrawn_relation_does_not_retain_stale_adoption_flag(db_session):
    caller, recalled, evidence, source = await _fixture(db_session, relation="accepted")
    await attach_platform_state(db_session, caller, evidence, recalled)
    assert evidence[0].platform_state["adoption_status"] == "adopted"
    source.replacement_asset_id = None
    await db_session.commit()
    await attach_platform_state(db_session, caller, evidence, recalled)
    assert evidence[0].platform_state["adoption_status"] == "unknown"


async def test_concurrent_pointer_change_does_not_mark_old_evidence_current(db_session):
    from sqlalchemy import update

    caller, recalled, evidence, _ = await _fixture(db_session, relation="accepted")
    target = recalled[0].asset
    previous = target.current_version_id
    await db_session.execute(
        update(KnowledgeAsset)
        .where(KnowledgeAsset.id == target.id)
        .values(current_version_id=uuid.uuid4())
        .execution_options(synchronize_session=False)
    )
    await db_session.commit()
    assert target.current_version_id == previous
    await attach_platform_state(db_session, caller, evidence, recalled)
    assert evidence[0].platform_state["version_selection"] == "unknown"
    assert evidence[0].platform_state["adoption_status"] == "unknown"
