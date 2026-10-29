"""Cached asset state cannot overwrite a terminal decision made elsewhere."""

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from app.models.knowledge import KnowledgeAsset
from app.schemas.lifecycle import ArchiveConfirmBody
from app.schemas.permission import CallerContext
from app.seed.dev_seed import KA_COMPANY_L2, USER_BOSS
from app.services.knowledge_lifecycle import delete_asset
from app.services.lifecycle import archive_confirm
from app.services.weknora_client import NullWeKnoraClient


@pytest.mark.parametrize("command", ["archive", "delete"])
async def test_stale_asset_cannot_override_or_repeat_deletion(db_session, command):
    cached = await db_session.get(KnowledgeAsset, KA_COMPANY_L2)
    assert cached.asset_status == "active"
    await db_session.execute(
        update(KnowledgeAsset)
        .where(KnowledgeAsset.id == cached.id)
        .values(asset_status="deleted")
        .execution_options(synchronize_session=False)
    )
    await db_session.commit()
    assert cached.asset_status == "active"
    caller = CallerContext(
        user_id=USER_BOSS, is_active=True, active_company_roles={"boss"}, active_project_ids=set()
    )
    with pytest.raises(HTTPException) as error:
        if command == "archive":
            await archive_confirm(
                db_session, caller, cached.id, ArchiveConfirmBody(reason="stale"), "state-test"
            )
        else:
            await delete_asset(
                db_session,
                caller,
                cached.id,
                reason="stale",
                weknora=NullWeKnoraClient(),
                trace_id="state-test",
                weknora_is_enabled=lambda: False,
            )
    assert error.value.status_code in {404, 409}
    await db_session.rollback()
    final = await db_session.get(KnowledgeAsset, KA_COMPANY_L2, populate_existing=True)
    assert final.asset_status == "deleted"
