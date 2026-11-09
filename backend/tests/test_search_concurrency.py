"""Request responsiveness and bounded SQL, using synthetic data and local clients."""

import asyncio
import threading
import uuid

import pytest
from sqlalchemy import event
from test_search_api import FakeSearchWeKnora

from app.main import app
from app.models.identity import User
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetVersion
from app.models.knowledge_directory import KnowledgeDirectory
from app.seed.dev_seed import DEV_PASSWORD, PROJECT_ALPHA, USER_CONSULTANT
from app.services import directories, passwords
from app.services.weknora_client import get_weknora_client


@pytest.mark.parametrize("email", ["consultant.a@dev.local", "unknown@dev.local"])
async def test_password_login_leaves_event_loop_available(client, monkeypatch, email):
    started = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    original = passwords._pbkdf2

    def slow_verification(*args):
        loop.call_soon_threadsafe(started.set)
        # A watchdog bounds the baseline failure even if the event loop is blocked.
        if not release.wait(3):
            raise AssertionError("password verification blocked unrelated requests")
        return original(*args)

    monkeypatch.setattr(passwords, "_pbkdf2", slow_verification)
    pending = asyncio.create_task(
        client.post("/api/v1/auth/login", json={"email": email, "password": DEV_PASSWORD})
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=5)
        health = await asyncio.wait_for(client.get("/health"), timeout=1)
        assert health.status_code == 200
        assert not pending.done(), "the unrelated request must finish during password verification"
    finally:
        release.set()
        result = await pending
    assert result.status_code == (200 if email.startswith("consultant") else 401)


@pytest.mark.parametrize("change", ["disable", "reset_password"])
async def test_login_rechecks_credentials_after_async_verification(
    client, db_session, monkeypatch, change
):
    entered = asyncio.Event()
    release = asyncio.Event()
    original = passwords.verify_password_async

    async def verification(*args):
        entered.set()
        await release.wait()
        return await original(*args)

    monkeypatch.setattr(passwords, "verify_password_async", verification)
    pending = asyncio.create_task(
        client.post(
            "/api/v1/auth/login",
            json={"email": "consultant.a@dev.local", "password": DEV_PASSWORD},
        )
    )
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        user = await db_session.get(User, USER_CONSULTANT)
        if change == "disable":
            user.status = "inactive"
        else:
            user.password_hash = passwords.hash_password("synthetic-replacement-password")
        await db_session.commit()
    finally:
        release.set()
        response = await pending
    assert response.status_code == 401
    assert response.json()["detail"]["denied_reason"] == "invalid_credentials"
    assert "kap_session=" not in response.headers.get("set-cookie", "")


@pytest.mark.parametrize("count", [1, 12])
async def test_search_reads_directory_snapshot_once(client, db_session, count):
    child_key = "company.methodology.synthetic"
    db_session.add(
        KnowledgeDirectory(
            directory_key=child_key,
            library_key="company",
            scope="company",
            parent_key="company.methodology",
            display_name="合成子目录",
            normalized_name="合成子目录",
            default_confidentiality="L2",
            created_by=USER_CONSULTANT,
        )
    )
    keys = [child_key, "project.deliverables", "company.removed_directory", None]
    assets = []
    docs = []
    for index in range(count):
        key = keys[index % len(keys)]
        project_id = PROJECT_ALPHA if key == "project.deliverables" else None
        asset = KnowledgeAsset(
            id=uuid.uuid4(),
            title=f"合成容量资料 {index}",
            scope="project" if project_id else "company",
            zone="asset",
            asset_type="deliverable",
            owner_user_id=USER_CONSULTANT,
            maintainer_user_id=USER_CONSULTANT,
            project_id=project_id,
            visibility="project_only" if project_id else "company_public",
            confidentiality_level="L2",
            ai_access_level="A1",
            asset_status="active",
        )
        version = KnowledgeAssetVersion(
            id=uuid.uuid4(),
            asset_id=asset.id,
            version_no="v1",
            version_status="active",
            created_by=USER_CONSULTANT,
            directory_key=key,
            weknora_kb_id=f"wk-kb-proj-{project_id}" if project_id else "wk-kb-company",
            weknora_doc_id=f"audit-doc-{asset.id}",
            index_status="indexed",
        )
        asset.versions.append(version)
        asset.current_version_id = version.id
        db_session.add(asset)
        assets.append((asset, version))
        docs.append(
            {
                "knowledge_id": version.weknora_doc_id,
                "kb_id": version.weknora_kb_id,
                "content": "合成内容",
            }
        )
    await db_session.commit()
    expected = {
        str(asset.id): await directories.display_path(
            db_session, directories.version_directory_key(version), asset.project_id
        )
        for asset, version in assets
    }
    counts = {"naming_rule_revisions": 0, "knowledge_directories": 0}

    def count_queries(_conn, _cursor, statement, _parameters, _context, _executemany):
        for table in counts:
            if f"FROM {table}" in statement:
                counts[table] += 1

    engine = db_session.bind.sync_engine
    event.listen(engine, "before_cursor_execute", count_queries)
    app.dependency_overrides[get_weknora_client] = lambda: FakeSearchWeKnora(docs)
    try:
        response = await client.post(
            "/api/v1/knowledge/search",
            headers={"X-Dev-User-Id": str(USER_CONSULTANT)},
            json={"query": "unique-synthetic-query", "intent": "search"},
        )
        assert response.status_code == 200, response.text
        actual = {card["asset_id"]: card["directory_path"] for card in response.json()["cards"]}
        assert actual == expected
        assert counts == {"naming_rule_revisions": 1, "knowledge_directories": 1}
    finally:
        event.remove(engine, "before_cursor_execute", count_queries)
        app.dependency_overrides.pop(get_weknora_client, None)
