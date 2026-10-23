"""Company third-level directories reuse versioned directory governance."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.naming import NamingRuleConfig
from app.seed.dev_seed import (
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
    USER_DIRECTOR,
    USER_PROJECT_MANAGER,
)
from app.services.directories import default_directory_config


def child(**changes):
    return {
        **default_directory_config()[0],
        "directory_key": f"company.custom_{uuid.uuid4().hex}",
        "parent_key": "company.introduction",
        "display_name": "宣传模板",
        "naming_code": "宣传模板",
        **changes,
    }


@pytest.mark.parametrize(
    "invalid",
    [
        {"parent_key": None},
        {"parent_key": "project.deliverables"},
        {"parent_key": "company.missing"},
        {"scope": "project"},
        {"directory_key": "company.uncontrolled"},
    ],
)
def test_rejects_invalid_company_child(invalid):
    with pytest.raises(ValidationError):
        NamingRuleConfig(directories=[*default_directory_config(), child(**invalid)])


def test_rejects_duplicate_names_and_fourth_level():
    item = child()
    for extra in [child(), child(parent_key=item["directory_key"], display_name="四级")]:
        with pytest.raises(ValidationError):
            NamingRuleConfig(directories=[*default_directory_config(), item, extra])


def test_parent_cannot_be_disabled_with_active_child():
    rows = default_directory_config()
    rows[0]["enabled"] = False
    with pytest.raises(ValidationError):
        NamingRuleConfig(directories=[*rows, child()])


@pytest.mark.parametrize(
    "user,allowed",
    [
        (USER_BOSS, True),
        (USER_DIRECTOR, True),
        (USER_CONSULTANT, False),
        (USER_ADMIN_ONLY, False),
        (USER_PROJECT_MANAGER, False),
    ],
)
async def test_create_publish_browse_child_permissions(client, user, allowed):
    headers = {"X-Dev-User-Id": str(user)}
    boss = {"X-Dev-User-Id": str(USER_BOSS)}
    center = await client.get("/api/v1/admin/naming-rules", headers=boss)
    initial = center.json()
    item = child()
    rows = [*initial["draft"]["config"]["directories"], item]
    result = await client.put(
        "/api/v1/admin/naming-rules/draft",
        headers=headers,
        json={
            "expected_base_version": initial["published"]["version"],
            "expected_draft_updated_at": initial["draft"]["updated_at"],
            "directories": rows,
        },
    )
    assert result.status_code == (200 if allowed else 403), result.text
    if not allowed:
        return
    # Draft directories are not available until explicitly published.
    visible = await client.get("/api/v1/knowledge/directories?scope=company", headers=boss)
    assert item["directory_key"] not in {row["directory_key"] for row in visible.json()["items"]}
    published = await client.post(
        "/api/v1/admin/naming-rules/publish",
        headers=headers,
        json={
            "expected_base_version": initial["published"]["version"],
            "expected_draft_updated_at": result.json()["updated_at"],
        },
    )
    assert published.status_code == 200, published.text
    visible = await client.get("/api/v1/knowledge/directories?scope=company", headers=boss)
    row = next(
        row for row in visible.json()["items"] if row["directory_key"] == item["directory_key"]
    )
    assert row["parent_key"] == "company.introduction"
    assert row["display_path"] == "公司库 / 00 公司介绍 / 宣传模板"
    options = await client.get("/api/v1/naming-options?scope=company", headers=boss)
    option = next(
        row
        for row in options.json()["directories"]
        if row["directory_key"] == item["directory_key"]
    )
    assert option["display_name"] == "00 公司介绍 / 宣传模板"
    listed = await client.get(
        f"/api/v1/knowledge?scope=company&directory_key={item['directory_key']}", headers=boss
    )
    assert listed.status_code == 200, listed.text
