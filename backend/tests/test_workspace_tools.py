"""Real catalogue projections keep workspace model tools inside current grants."""

import json
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models.knowledge import KnowledgeAsset, KnowledgeAssetSummary
from app.schemas.permission import CallerContext
from app.seed.dev_seed import KA_COMPANY_L2, USER_ADMIN_ONLY, USER_CONSULTANT
from app.services import workspace_tools


def caller(user=USER_CONSULTANT, role="consultant"):
    return CallerContext(
        user_id=user,
        is_active=True,
        active_company_roles={role},
        active_project_ids=set(),
    )


async def test_search_redacts_and_rechecks_live_source(db_session):
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    asset.title = "访谈提纲 电话13800138000"
    summaries = list(
        await db_session.scalars(
            select(KnowledgeAssetSummary).where(
                KnowledgeAssetSummary.asset_id == asset.id,
                KnowledgeAssetSummary.version_id == asset.current_version_id,
            )
        )
    )
    if not any(summary.summary_type == "redacted_summary" for summary in summaries):
        safe = KnowledgeAssetSummary(
            asset_id=asset.id,
            version_id=asset.current_version_id,
            summary_type="redacted_summary",
            content="",
        )
        db_session.add(safe)
        summaries.append(safe)
    for summary in summaries:
        summary.content = "访谈提纲中的联系方式13800138000"
    await db_session.commit()
    result = await workspace_tools.search_context(db_session, caller(), "company", "访谈提纲")
    assert result
    assert "13800138000" not in json.dumps(result, ensure_ascii=False)
    assert result[0]["source_type"] == "summary"
    assert await workspace_tools.sources_available(db_session, caller(), result)
    for summary in summaries:
        summary.content = "访谈提纲的修订摘要"
    await db_session.commit()
    assert not await workspace_tools.sources_available(db_session, caller(), result)
    result = await workspace_tools.search_context(db_session, caller(), "company", "访谈提纲")
    assert await workspace_tools.sources_available(db_session, caller(), result)
    asset.confidentiality_level = "L5"
    await db_session.commit()
    assert not await workspace_tools.sources_available(db_session, caller(), result)
    assert await workspace_tools.search_context(db_session, caller(), "company", "访谈提纲") == []


async def test_contexts_never_grant_system_admin_or_unjoined_projects(db_session):
    assert await workspace_tools.available_contexts(db_session, caller()) == [
        {"key": "company", "label": "公司知识库"}
    ]
    with pytest.raises(HTTPException) as error:
        await workspace_tools.available_contexts(db_session, caller(USER_ADMIN_ONLY, "admin"))
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        await workspace_tools.check_context(db_session, caller(), f"project:{uuid.uuid4()}")
    assert error.value.status_code == 404
    assert not await workspace_tools.sources_available(db_session, caller(), [{"asset_id": "bad"}])
