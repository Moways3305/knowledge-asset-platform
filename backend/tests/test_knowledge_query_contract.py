from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models.identity import ProjectMember, User
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.schemas.permission import AccessLayer
from app.seed.dev_seed import (
    PROJECT_ALPHA,
    PROJECT_BETA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_CONSULTANT_ADMIN,
)
from app.services.permission import build_caller_context, decide, discovery_filter
from app.services.permission_rules import load_access_policy

KNOWLEDGE = "/api/v1/knowledge"


def _headers(user_id):
    return {"X-Dev-User-Id": str(user_id)}


def _asset(
    title: str,
    *,
    scope: str = "company",
    project_id=None,
    zone: str = "asset",
    asset_type: str = "case",
    confidentiality_level: str = "L2",
    asset_status: str = "active",
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> KnowledgeAsset:
    return KnowledgeAsset(
        title=title,
        scope=scope,
        project_id=project_id,
        zone=zone,
        asset_type=asset_type,
        owner_user_id=USER_CONSULTANT,
        visibility="project_only" if scope == "project" else "public",
        confidentiality_level=confidentiality_level,
        ai_access_level="A1",
        asset_status=asset_status,
        created_at=created_at or datetime.now(timezone.utc),
        updated_at=updated_at or datetime.now(timezone.utc),
    )


async def test_legacy_request_uses_bounded_first_page(client):
    response = await client.get(KNOWLEDGE, headers=_headers(USER_CONSULTANT))
    assert response.status_code == 200
    body = response.json()
    assert body["page"] == 1
    assert body["page_size"] == 50
    assert len(body["items"]) <= 50
    assert body["total"] >= len(body["items"])
    assert body["has_next"] is (body["total"] > 50)


@pytest.mark.parametrize(
    "params",
    [
        {"page": 0},
        {"page_size": 0},
        {"page_size": 101},
        {"sort_by": "owner_user_id"},
        {"sort_direction": "sideways"},
        {"scope": "all"},
        {"zone": "unknown"},
        {"asset_type": "unknown"},
        {"asset_status": "processing"},
        {"confidentiality_level": "L6"},
        {"keyword": "   "},
        {"created_from": "2026-01-01T00:00:00"},
        {
            "created_from": "2026-02-01T00:00:00Z",
            "created_to": "2026-01-01T00:00:00Z",
        },
        {
            "updated_from": "2026-02-01T00:00:00Z",
            "updated_to": "2026-01-01T00:00:00Z",
        },
    ],
)
async def test_invalid_query_parameters_return_422(client, params):
    response = await client.get(KNOWLEDGE, params=params, headers=_headers(USER_CONSULTANT))
    assert response.status_code == 422


async def test_combined_filters_and_stable_pagination(client, db_session):
    timestamp = datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc)
    titles = [
        "PBC67-PAGE Delta",
        "PBC67-PAGE Alpha",
        "PBC67-PAGE Echo",
        "PBC67-PAGE Charlie",
        "PBC67-PAGE Bravo",
    ]
    db_session.add_all(
        [_asset(title, created_at=timestamp, updated_at=timestamp) for title in titles]
    )
    db_session.add(_asset("PBC67-PAGE wrong zone", zone="material", created_at=timestamp))
    await db_session.commit()

    common = {
        "keyword": "PBC67-PAGE",
        "scope": "company",
        "zone": "asset",
        "asset_type": "case",
        "asset_status": "active",
        "confidentiality_level": "L2",
        "created_from": (timestamp - timedelta(minutes=1)).isoformat(),
        "created_to": (timestamp + timedelta(minutes=1)).isoformat(),
        "updated_from": (timestamp - timedelta(minutes=1)).isoformat(),
        "updated_to": (timestamp + timedelta(minutes=1)).isoformat(),
        "sort_by": "title",
        "sort_direction": "asc",
        "page_size": 2,
    }
    pages = []
    for page in (1, 2, 3):
        response = await client.get(
            KNOWLEDGE,
            params={**common, "page": page},
            headers=_headers(USER_CONSULTANT),
        )
        assert response.status_code == 200, response.text
        pages.append(response.json())

    assert [page["total"] for page in pages] == [5, 5, 5]
    assert [page["has_next"] for page in pages] == [True, True, False]
    returned = [item["title"] for page in pages for item in page["items"]]
    assert returned == sorted(titles, key=str.lower)
    assert len(returned) == len(set(returned))


async def test_sql_discovery_filter_matches_authoritative_decisions(db_session):
    assets = list((await db_session.execute(select(KnowledgeAsset))).scalars().all())
    policy = await load_access_policy(db_session)
    for user_id in (USER_CONSULTANT, USER_BOSS, USER_ADMIN_ONLY, USER_CONSULTANT_ADMIN):
        user = (
            await db_session.execute(
                select(User)
                .where(User.id == user_id)
                .options(selectinload(User.company_roles), selectinload(User.project_members))
            )
        ).scalar_one()
        caller = build_caller_context(user)
        expected = {
            asset.id
            for asset in assets
            if decide(caller, asset, AccessLayer.discovery, policy=policy).allowed
        }
        actual = set(
            (await db_session.execute(select(KnowledgeAsset.id).where(discovery_filter(caller))))
            .scalars()
            .all()
        )
        assert actual == expected


async def test_keyword_matches_tags_without_wildcard_expansion(client, db_session):
    tagged = _asset("Tag-only query asset")
    tagged.tags.append(KnowledgeAssetTag(tag_name="PBC67_100%"))
    db_session.add(tagged)
    await db_session.commit()

    response = await client.get(
        KNOWLEDGE,
        params={"keyword": "PBC67_100%"},
        headers=_headers(USER_CONSULTANT),
    )
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["items"][0]["id"] == str(tagged.id)


async def test_unauthorized_l5_title_is_absent_from_items_and_total(client, db_session):
    secret_title = "PBC67-SECRET executive acquisition"
    db_session.add(_asset(secret_title, confidentiality_level="L5"))
    await db_session.commit()

    denied = await client.get(
        KNOWLEDGE,
        params={"keyword": "PBC67-SECRET"},
        headers=_headers(USER_CONSULTANT),
    )
    assert denied.status_code == 200
    assert denied.json()["total"] == 0
    assert secret_title not in denied.text

    allowed = await client.get(
        KNOWLEDGE,
        params={"keyword": "PBC67-SECRET"},
        headers=_headers(USER_BOSS),
    )
    assert allowed.status_code == 200
    assert allowed.json()["total"] == 1
    assert allowed.json()["items"][0]["title"] == secret_title


async def test_project_membership_filters_rows_before_count(client, db_session):
    alpha = _asset("PBC67-PROJECT Alpha", scope="project", project_id=PROJECT_ALPHA)
    beta = _asset("PBC67-PROJECT Beta", scope="project", project_id=PROJECT_BETA)
    db_session.add_all([alpha, beta])
    db_session.add(
        ProjectMember(
            user_id=USER_CONSULTANT_ADMIN,
            project_id=PROJECT_BETA,
            project_role="consultant",
            status="active",
        )
    )
    await db_session.commit()

    alpha_member = await client.get(
        KNOWLEDGE,
        params={"scope": "project", "keyword": "PBC67-PROJECT"},
        headers=_headers(USER_CONSULTANT),
    )
    assert alpha_member.json()["total"] == 1
    assert alpha_member.json()["items"][0]["id"] == str(alpha.id)

    beta_member = await client.get(
        KNOWLEDGE,
        params={"scope": "project", "keyword": "PBC67-PROJECT"},
        headers=_headers(USER_CONSULTANT_ADMIN),
    )
    assert beta_member.json()["total"] == 1
    assert beta_member.json()["items"][0]["id"] == str(beta.id)

    denied_context = await client.get(
        KNOWLEDGE,
        params={"scope": "project", "project_id": str(PROJECT_BETA)},
        headers=_headers(USER_CONSULTANT),
    )
    assert denied_context.status_code == 403


async def test_redacted_summary_projection_never_loads_ordinary_summary(client, db_session):
    asset = _asset("PBC67-REDACTED", confidentiality_level="L3")
    db_session.add(asset)
    await db_session.flush()
    version = KnowledgeAssetVersion(
        asset_id=asset.id,
        version_no="v1",
        version_status="active",
        created_by=USER_CONSULTANT,
    )
    db_session.add(version)
    await db_session.flush()
    asset.current_version_id = version.id
    db_session.add_all(
        [
            KnowledgeAssetSummary(
                asset_id=asset.id,
                version_id=version.id,
                summary_type="detailed",
                content="PBC67-UNSAFE-SUMMARY",
            ),
            KnowledgeAssetSummary(
                asset_id=asset.id,
                version_id=version.id,
                summary_type="redacted_summary",
                content="PBC67 safe summary",
            ),
        ]
    )
    await db_session.commit()

    response = await client.get(
        KNOWLEDGE,
        params={"keyword": "PBC67-REDACTED"},
        headers=_headers(USER_CONSULTANT),
    )
    assert response.status_code == 200
    assert response.json()["items"][0]["summary_text"] == "PBC67 safe summary"
    assert "PBC67-UNSAFE-SUMMARY" not in response.text
