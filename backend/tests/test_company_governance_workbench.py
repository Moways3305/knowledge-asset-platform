from app.seed.dev_seed import (
    KA_COMPANY_L2,
    KA_PROJECT_ALPHA,
    USER_ADMIN_ONLY,
    USER_BOSS,
    USER_CONSULTANT,
)

URL = "/api/v1/company-governance"


def headers(user=USER_BOSS):
    return {"X-Dev-User-Id": str(user)}


async def selection(client, asset_id):
    response = await client.get(URL + "?view=all", headers=headers())
    assert response.status_code == 200, response.text
    row = next(r for r in response.json()["items"] if r["asset_id"] == str(asset_id))
    return dict(
        asset_id=row["asset_id"],
        expected_status=row["asset_status"],
        expected_updated_at=row["updated_at"],
    )


async def test_archive_restore_and_stale_selection(client):
    item = await selection(client, KA_COMPANY_L2)
    body = dict(items=[item], action="archive", reason_code="historical", reason="历史参考")
    r = await client.post(URL + "/batch", json=body, headers=headers())
    assert r.status_code == 200, r.text
    assert r.json()["items"][0]["success"]
    r = await client.post(URL + "/batch", json=body, headers=headers())
    assert not r.json()["items"][0]["success"]
    r = await client.get(URL + "?view=archived", headers=headers())
    row = next(i for i in r.json()["items"] if i["asset_id"] == str(KA_COMPANY_L2))
    assert "历史参考" in row["archive_reason"]
    assert "storage_ref" not in r.text
    hidden = await client.get("/api/v1/knowledge/" + str(KA_COMPANY_L2), headers=headers())
    assert hidden.status_code == 404
    body.update(
        action="restore",
        items=[
            dict(
                asset_id=row["asset_id"],
                expected_status="archived",
                expected_updated_at=row["updated_at"],
            )
        ],
    )
    restored = await client.post(URL + "/batch", json=body, headers=headers())
    assert restored.json()["items"][0]["success"], restored.text
    await selection(client, KA_COMPANY_L2)


async def test_company_boundary_and_roles(client):
    for user in (USER_CONSULTANT, USER_ADMIN_ONLY):
        assert (await client.get(URL, headers=headers(user))).status_code == 403
    item = await selection(client, KA_COMPANY_L2)
    foreign = dict(item, asset_id=str(KA_PROJECT_ALPHA))
    r = await client.post(
        URL + "/batch",
        headers=headers(),
        json=dict(items=[foreign, item], action="archive", reason_code="other", reason="复核"),
    )
    assert r.status_code == 200, r.text
    assert [i["success"] for i in r.json()["items"]] == [False, True]


async def test_batch_validation(client):
    item = await selection(client, KA_COMPANY_L2)
    body = dict(items=[item], action="archive", reason_code="superseded", reason="更新")
    assert (await client.post(URL + "/batch", headers=headers(), json=body)).status_code == 422
    body.update(reason_code="other", reason="   ")
    assert (await client.post(URL + "/batch", headers=headers(), json=body)).status_code == 422
    body.update(reason="复核", items=[item, item])
    assert (await client.post(URL + "/batch", headers=headers(), json=body)).status_code == 422


async def test_stale_timestamp_does_not_archive(client):
    item = await selection(client, KA_COMPANY_L2)
    stale = dict(item, expected_updated_at="2000-01-01T00:00:00Z")
    response = await client.post(
        URL + "/batch",
        headers=headers(),
        json=dict(items=[stale], action="archive", reason_code="other", reason="复核"),
    )
    assert response.status_code == 200
    assert not response.json()["items"][0]["success"]
    assert await selection(client, KA_COMPANY_L2) == item


async def test_project_replacement_does_not_archive_company_asset(client):
    item = await selection(client, KA_COMPANY_L2)
    response = await client.post(
        URL + "/batch",
        headers=headers(),
        json=dict(
            items=[item],
            action="archive",
            reason_code="superseded",
            reason="新版替代",
            replacement_asset_id=str(KA_PROJECT_ALPHA),
        ),
    )
    assert response.status_code == 200
    assert not response.json()["items"][0]["success"]
    assert await selection(client, KA_COMPANY_L2) == item
