"""知识库重建迁移（换 embedding 模型）集成测试。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.main import app
from app.models.indexing_job import IndexingOperationJob
from app.models.ingest import IngestTask
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetChunk, KnowledgeAssetVersion
from app.models.weknora import WeknoraKbMapping
from app.seed.dev_seed import USER_ADMIN_ONLY, USER_CONSULTANT, USER_DIRECTOR
from app.services.storage import LocalFileStorage, get_storage
from app.services.weknora_client import WeKnoraError, get_weknora_client
from app.services.weknora_models import _model_ref

BASE = "/api/v1/admin/weknora"


def _hdr(uid):
    return {"X-Dev-User-Id": str(uid)}


class FakeMigrateWK:
    """迁移用 fake 底座：记录建库 / 初始化 / 重传 / 删库。"""

    def __init__(self, *, fail_docs: set[str] | None = None, available: bool = True) -> None:
        self.models = [
            {
                "id": "emb-new",
                "name": "embedding-new",
                "type": "Embedding",
                "source": "remote",
                "status": "active",
                "parameters": {"base_url": "https://controlled.invalid/v1"},
                "credentials": {"api_key": {"configured": True}},
            },
            {
                "id": "chat-1",
                "name": "qwen-plus",
                "type": "KnowledgeQA",
                "source": "remote",
                "status": "active",
            },
            {
                "id": "vlm-1",
                "name": "glm-4.6v",
                "type": "VLLM",
                "source": "remote",
                "status": "active",
            },
        ]
        self.create_calls: list[str] = []
        self.init_calls: list[str] = []
        self.update_config_calls: list[str] = []
        self.reparse_calls: list[dict] = []
        self.deleted_kbs: list[str] = []
        self.fail_docs = fail_docs or set()
        self.available = available
        self._kb = 0
        self._doc = 0

    async def list_models(self, *, trace_id=None):
        return self.models

    async def get_model(self, model_id, *, trace_id=None):
        return next(model for model in self.models if model["id"] == model_id)

    async def get_model_credentials(self, model_id, *, trace_id=None):
        model = await self.get_model(model_id, trace_id=trace_id)
        return {"fields": model.get("credentials", {})}

    async def test_embedding_model(self, **_):
        return {"available": self.available}

    async def create_kb(self, *, name, embedding_model_id, trace_id=None):
        self.create_calls.append(embedding_model_id)
        self._kb += 1
        return f"new-kb-{self._kb}"

    async def initialize_kb(self, kb_id, *, trace_id=None, **kw):
        self.init_calls.append(kb_id)
        return None

    async def get_kb(self, kb_id, *, trace_id=None):
        return {
            "summary_model_id": "chat-1",
            "embedding_model_id": "emb-new",
            "chunking_config": {},
            "vlm_config": {"enabled": False},
            "asr_config": {},
            "storage_provider_config": {},
            "extract_config": {},
            "question_generation_config": {},
        }

    async def update_initialization_config(self, kb_id, *, config, trace_id=None):
        self.update_config_calls.append(kb_id)
        return {"success": True}

    async def reparse_knowledge(
        self,
        *,
        kb_id,
        knowledge_id,
        content,
        file_name,
        mime,
        metadata=None,
        channel=None,
        trace_id=None,
    ):
        if knowledge_id in self.fail_docs:
            raise WeKnoraError("weknora_down", "底座不可用")
        self.reparse_calls.append(
            {
                "kb_id": kb_id,
                "knowledge_id": knowledge_id,
                "content": content,
                "file_name": file_name,
            }
        )
        self._doc += 1
        return {"id": f"new-doc-{self._doc}", "parse_status": "processing", "file_hash": "h"}

    async def delete_kb(self, kb_id, *, trace_id=None):
        self.deleted_kbs.append(kb_id)


async def _seed_kb_and_assets(db_session, storage, *, n: int = 2):
    owner = USER_DIRECTOR  # 无 seed 个人资产的用户，避免混入迁移范围
    refs = [storage.save(f"内容{i}".encode(), original_name=f"doc{i}.txt") for i in range(n)]
    mp = WeknoraKbMapping(
        scope="personal",
        owner_user_id=owner,
        weknora_kb_id="old-kb-1",
        embedding_model_id="emb-old",
        kb_name="personal_x_kb",
        status="active",
    )
    db_session.add(mp)
    await db_session.flush()
    versions = []
    for i, ref in enumerate(refs):
        asset = KnowledgeAsset(
            title=f"迁移资产{i}",
            scope="personal",
            zone="asset",
            asset_type="methodology",
            owner_user_id=owner,
            maintainer_user_id=owner,
            visibility="confidential",
            confidentiality_level="L3",
            ai_access_level="A1",
            asset_status="active",
        )
        db_session.add(asset)
        await db_session.flush()
        version = KnowledgeAssetVersion(
            asset_id=asset.id,
            version_no="v1",
            version_status="active",
            created_by=USER_CONSULTANT,
            index_status="indexed",
            weknora_kb_id="old-kb-1",
            weknora_doc_id=f"old-doc-{i + 1}",
            weknora_parse_status="failed",
        )
        db_session.add(version)
        await db_session.flush()
        db_session.add(
            IngestTask(
                source="local",
                source_file_ref=ref,
                source_file_name=f"doc{i}.txt",
                source_file_mime_type="text/plain",
                created_by=USER_CONSULTANT,
                target_scope="personal",
                status="completed",
                result_asset_id=asset.id,
                result_version_id=version.id,
            )
        )
        versions.append(version)
    await db_session.commit()
    return mp, versions


def _refs(fake: FakeMigrateWK) -> dict[str, str]:
    return {m["name"]: _model_ref(m["id"]) for m in fake.models}


@pytest.fixture
def storage(tmp_path) -> LocalFileStorage:
    return LocalFileStorage(str(tmp_path))


async def _enable(monkeypatch, fake, storage):
    monkeypatch.setattr("app.api.weknora_admin.weknora_enabled", lambda: True)
    monkeypatch.setattr("app.services.kb_migration.weknora_enabled", lambda: True)
    app.dependency_overrides[get_weknora_client] = lambda: fake
    app.dependency_overrides[get_storage] = lambda: storage


def _disable() -> None:
    app.dependency_overrides.pop(get_weknora_client, None)
    app.dependency_overrides.pop(get_storage, None)


async def _migrate(client, mapping_id, refs):
    return await client.post(
        f"{BASE}/kb-configs/{mapping_id}/migrate",
        headers=_hdr(USER_ADMIN_ONLY),
        json={
            "embedding_model_ref": refs["embedding-new"],
            "chat_model_ref": refs["qwen-plus"],
            "multimodal_model_ref": refs["glm-4.6v"],
        },
    )


async def test_migrate_kb_success(client, db_session, monkeypatch, storage, sessionmaker_fixture):
    fake = FakeMigrateWK()
    await _enable(monkeypatch, fake, storage)
    try:
        mp, versions = await _seed_kb_and_assets(db_session, storage)
        from app.services.source_content import resolve_version_source_task

        task = await resolve_version_source_task(
            db_session, asset_id=versions[0].asset_id, version_id=versions[0].id
        )
        assert task is not None, "seed 任务应能被同源解析"
        assert task.source_file_ref
        async with sessionmaker_fixture() as other:
            cross = await resolve_version_source_task(
                other, asset_id=versions[0].asset_id, version_id=versions[0].id
            )
            assert cross is not None, "跨 session 应能看到 seed 任务"
            cross1 = await resolve_version_source_task(
                other, asset_id=versions[1].asset_id, version_id=versions[1].id
            )
            assert cross1 is not None, "第二个版本的任务也应可见"
        r = await _migrate(client, mp.id, _refs(fake))

        assert r.status_code == 200, r.text
        print("MIGRATE_BODY", r.json(), "VERSION_IDS", [str(v.id) for v in versions])
        assert r.json()["job_status"] == "completed"
        await db_session.refresh(mp)
        assert mp.status == "active"
        assert mp.embedding_model_id == "emb-new"
        assert mp.weknora_kb_id == "new-kb-1"
        assert mp.migration_state is None
        assert fake.create_calls == ["emb-new"]
        assert fake.init_calls == []  # 不再走 source/modelName 初始化，避免改写模型记录
        assert fake.update_config_calls == ["new-kb-1"]
        assert fake.deleted_kbs == ["old-kb-1"]
        # 阶段2：迁移重传的是治理文本（md），不是原件字节。
        assert fake.reparse_calls
        assert all(call["file_name"].endswith(".md") for call in fake.reparse_calls)
        migrated_text = b"".join(call["content"] for call in fake.reparse_calls)
        assert "内容0".encode() in migrated_text
        assert "内容1".encode() in migrated_text
        # 阶段3：迁移后 chunk 注册表已落库（两个版本各至少一块）。
        chunks = list(
            (
                await db_session.execute(
                    select(KnowledgeAssetChunk).where(
                        KnowledgeAssetChunk.version_id.in_([v.id for v in versions])
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(chunks) >= 2
        for v in versions:
            await db_session.refresh(v)
            assert v.weknora_kb_id == "new-kb-1"
        assert "old-kb-1" not in r.text and "emb-old" not in r.text
    finally:
        _disable()


async def test_migration_is_blocked_before_enqueue_when_embedding_is_unavailable(
    client, db_session, monkeypatch, storage
):
    fake = FakeMigrateWK(available=False)
    await _enable(monkeypatch, fake, storage)
    try:
        mp, _versions = await _seed_kb_and_assets(db_session, storage)
        response = await _migrate(client, mp.id, _refs(fake))
        assert response.status_code == 409
        assert response.json()["detail"]["denied_reason"] == "weknora_embedding_not_ready"
        jobs = (
            (
                await db_session.execute(
                    select(IndexingOperationJob).where(
                        IndexingOperationJob.operation_type == "kb_migrate"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert jobs == []
        await db_session.refresh(mp)
        assert mp.weknora_kb_id == "old-kb-1"
        assert mp.embedding_model_id == "emb-old"
    finally:
        _disable()


async def test_migrate_partial_failure_is_resumable(client, db_session, monkeypatch, storage):
    fake = FakeMigrateWK(fail_docs={"old-doc-1"})
    await _enable(monkeypatch, fake, storage)
    try:
        mp, versions = await _seed_kb_and_assets(db_session, storage)
        r = await _migrate(client, mp.id, _refs(fake))
        assert r.json()["job_status"] == "completed_with_errors"

        await db_session.refresh(mp)
        assert mp.status == "migrating"
        assert mp.migration_state["to"] == "new-kb-1"
        await db_session.refresh(versions[0])
        assert versions[0].weknora_kb_id == "old-kb-1"  # 失败版本仍在旧库
        await db_session.refresh(versions[1])
        assert versions[1].weknora_kb_id == "new-kb-1"

        # 修复底座后续跑：mapping 保持 migrating，复用新库继续迁移失败版本。
        fake.fail_docs = set()
        r2 = await _migrate(client, mp.id, _refs(fake))
        assert r2.json()["job_status"] == "completed"
        await db_session.refresh(mp)
        assert mp.status == "active"
        assert mp.migration_state is None
        assert fake.deleted_kbs == ["old-kb-1"]
        await db_session.refresh(versions[0])
        assert versions[0].weknora_kb_id == "new-kb-1"
    finally:
        _disable()


async def test_migrating_mapping_blocks_new_ingest_and_config(db_session):
    mp = WeknoraKbMapping(
        scope="personal",
        owner_user_id=USER_CONSULTANT,
        weknora_kb_id="old-kb-1",
        embedding_model_id="emb-old",
        kb_name="personal_x_kb",
        status="migrating",
    )
    db_session.add(mp)
    await db_session.commit()

    from app.services.weknora_kb import resolve_or_create_kb
    from app.services.weknora_model_selection import ResolvedModels

    with pytest.raises(WeKnoraError) as ei:
        await resolve_or_create_kb(
            db_session,
            FakeMigrateWK(),
            scope="personal",
            owner_user_id=USER_CONSULTANT,
            project_id=None,
            models=ResolvedModels(
                embedding_model_id="emb-new", explicit_embedding=False, chat_model_id="chat-1"
            ),
            trace_id=None,
        )
    assert ei.value.code == "weknora_kb_migrating"


async def test_migrate_job_level_failure_marks_failed_and_keeps_old_kb(
    client, db_session, monkeypatch, storage
):
    fake = FakeMigrateWK()

    async def boom(*_a, **_k):
        raise WeKnoraError("weknora_down", "底座不可用")

    fake.create_kb = boom
    await _enable(monkeypatch, fake, storage)
    try:
        mp, _versions = await _seed_kb_and_assets(db_session, storage)
        r = await _migrate(client, mp.id, _refs(fake))

        assert r.status_code == 200, r.text
        assert r.json()["job_status"] == "failed"  # 不卡 running
        await db_session.refresh(mp)
        assert mp.status == "active"  # 建库失败：mapping 未切换
        assert mp.weknora_kb_id == "old-kb-1"
        assert mp.migration_state is None
    finally:
        _disable()
