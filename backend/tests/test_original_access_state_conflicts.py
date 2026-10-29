"""A cached pending request cannot overwrite a committed approval decision."""

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from test_permission_runtime import TIMEOUT, _set_numeric

from app.db.utils import utc_now
from app.models.audit import AuditEvent
from app.models.knowledge import KnowledgeAsset
from app.models.original_access import AccessGrant, OriginalAccessRequest
from app.schemas.permission import CallerContext
from app.seed.dev_seed import KA_COMPANY_L2, USER_BOSS, USER_CONSULTANT
from app.services import original_access
from app.services.permission_rules import load_access_policy


async def pending(session):
    request = OriginalAccessRequest(
        asset_id=KA_COMPANY_L2,
        requester_user_id=USER_CONSULTANT,
        status="pending",
        created_at=utc_now() - timedelta(hours=2),
    )
    session.add(request)
    await session.commit()
    return request


def reviewer():
    return CallerContext(
        user_id=USER_BOSS, is_active=True, active_company_roles={"boss"}, active_project_ids=set()
    )


@pytest.mark.parametrize("action,committed", [("approve", "rejected"), ("reject", "approved")])
async def test_manual_decision_refreshes_stale_pending_identity(db_session, action, committed):
    request = await pending(db_session)
    await db_session.execute(
        update(OriginalAccessRequest)
        .where(OriginalAccessRequest.id == request.id)
        .values(status=committed, review_note="first decision")
        .execution_options(synchronize_session=False)
    )
    await db_session.commit()
    assert request.status == "pending"
    operation = (
        original_access.approve_request if action == "approve" else original_access.reject_request
    )
    with pytest.raises(HTTPException) as error:
        await operation(db_session, reviewer(), request.id, "late decision", "stale-request-test")
    assert error.value.status_code == 409
    assert error.value.detail["denied_reason"] == "request_already_finalized"
    await db_session.refresh(request)
    assert request.status == committed
    assert request.review_note == "first decision"
    assert (await db_session.scalars(select(AccessGrant))).all() == []
    assert (await db_session.scalars(select(AuditEvent))).all() == []


async def test_auto_decision_refreshes_stale_rejected_request(db_session):
    request = await pending(db_session)
    await db_session.execute(
        update(OriginalAccessRequest)
        .where(OriginalAccessRequest.id == request.id)
        .values(status="rejected", review_note="human rejection")
        .execution_options(synchronize_session=False)
    )
    await db_session.commit()
    assert request.status == "pending"
    outcome = await original_access._auto_approve_one(
        db_session,
        request.id,
        now=utc_now(),
        days=7,
        timeout_hours=1,
        policy=await load_access_policy(db_session),
        trace_id="stale-auto-test",
    )
    assert outcome == "skipped_invalid"
    await db_session.refresh(request)
    assert request.status == "rejected"
    assert request.review_note == "human rejection"
    assert (await db_session.scalars(select(AccessGrant))).all() == []
    assert (await db_session.scalars(select(AuditEvent))).all() == []


async def test_auto_batch_rechecks_rejection_after_listing(db_session, monkeypatch):
    request = await pending(db_session)
    request_id = request.id
    await _set_numeric(db_session, TIMEOUT, value_number=1, enabled=True)
    original = original_access._auto_approve_one

    async def rejected_before_lock(session, candidate_id, **kwargs):
        await session.execute(
            update(OriginalAccessRequest)
            .where(OriginalAccessRequest.id == candidate_id)
            .values(status="rejected", review_note="human won before lock")
            .execution_options(synchronize_session=False)
        )
        await session.commit()
        return await original(session, candidate_id, **kwargs)

    monkeypatch.setattr(original_access, "_auto_approve_one", rejected_before_lock)
    stats = await original_access.auto_approve_timed_out_original_access_requests(
        db_session, trace_id="list-before-lock-test"
    )
    assert stats["checked"] == 1 and stats["skipped_invalid"] == 1
    assert stats["approved"] == 0 and stats["errors"] == 0
    await db_session.refresh(request)
    assert request.id == request_id and request.status == "rejected"
    assert (await db_session.scalars(select(AccessGrant))).all() == []


async def test_auto_rechecks_timeout_eligibility_after_refresh(db_session):
    request = await pending(db_session)
    now = utc_now()
    await db_session.execute(
        update(OriginalAccessRequest)
        .where(OriginalAccessRequest.id == request.id)
        .values(created_at=now)
        .execution_options(synchronize_session=False)
    )
    await db_session.commit()
    outcome = await original_access._auto_approve_one(
        db_session,
        request.id,
        now=now,
        days=7,
        timeout_hours=1,
        policy=await load_access_policy(db_session),
        trace_id="stale-timeout-test",
    )
    assert outcome == "skipped_invalid"
    await db_session.refresh(request)
    assert request.status == "pending"
    assert (await db_session.scalars(select(AccessGrant))).all() == []


async def test_auto_batch_continues_after_rollback_expires_cached_requests(db_session, monkeypatch):
    from app.seed.dev_seed import KA_COMPANY_L4

    first = await pending(db_session)
    first_id = first.id
    asset = await db_session.get(KnowledgeAsset, KA_COMPANY_L4)
    asset.confidentiality_level = "L2"
    second = OriginalAccessRequest(
        asset_id=KA_COMPANY_L4,
        requester_user_id=USER_CONSULTANT,
        status="pending",
        created_at=utc_now() - timedelta(hours=1.5),
    )
    db_session.add(second)
    await db_session.commit()
    second_id = second.id
    await _set_numeric(db_session, TIMEOUT, value_number=1, enabled=True)
    ensure_grant = original_access._ensure_active_grant_for_request

    async def fail_first(session, **kwargs):
        if kwargs["req"].id == first_id:
            raise RuntimeError("synthetic first-item failure")
        return await ensure_grant(session, **kwargs)

    monkeypatch.setattr(original_access, "_ensure_active_grant_for_request", fail_first)
    stats = await original_access.auto_approve_timed_out_original_access_requests(
        db_session, trace_id="rollback-batch-test"
    )
    assert stats["checked"] == 2 and stats["errors"] == 1 and stats["approved"] == 1
    assert (await db_session.get(OriginalAccessRequest, first_id)).status == "pending"
    assert (await db_session.get(OriginalAccessRequest, second_id)).status == "approved"


async def test_approval_refreshes_asset_state_before_creating_grant(db_session):
    request = await pending(db_session)
    asset = await db_session.get(KnowledgeAsset, request.asset_id)
    await db_session.execute(
        update(KnowledgeAsset)
        .where(KnowledgeAsset.id == asset.id)
        .values(asset_status="deleted")
        .execution_options(synchronize_session=False)
    )
    await db_session.commit()
    assert asset.asset_status == "active"
    with pytest.raises(HTTPException) as error:
        await original_access.approve_request(
            db_session, reviewer(), request.id, "late approval", "stale-asset-test"
        )
    assert error.value.status_code == 409
    assert error.value.detail["denied_reason"] == "knowledge_asset_not_active"
    assert (await db_session.scalars(select(AccessGrant))).all() == []
