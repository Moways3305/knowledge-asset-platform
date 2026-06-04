"""知识资产核心模型测试（IMPLEMENT-02）。

覆盖：基本对象图创建、唯一约束、自引用、storage_ref 不外泄等。
使用内存 SQLite + seed 中的用户/项目作为外键引用对象。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

import app.schemas as schemas_pkg
from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetChunk,
    KnowledgeAssetFileObject,
    KnowledgeAssetSummary,
    KnowledgeAssetTag,
    KnowledgeAssetVersion,
)
from app.seed.dev_seed import PROJECT_ALPHA, USER_BOSS, USER_CONSULTANT


async def _make_asset(session, *, scope: str, owner=USER_CONSULTANT, project_id=None):
    """创建并提交一个最小资产（无版本），返回该资产。"""
    asset = KnowledgeAsset(
        title="测试资产",
        scope=scope,
        zone="material",
        asset_type="methodology",
        owner_user_id=owner,
        project_id=project_id,
        visibility="project_only",
        confidentiality_level="L2",
        ai_access_level="A1",
        asset_status="active",
    )
    session.add(asset)
    await session.commit()
    return asset


async def test_create_personal_asset_with_version_summary_tag(db_session):
    """可创建 personal 资产 + version + summary + tag，并能查询回来。"""
    asset = KnowledgeAsset(
        title="个人方法论",
        scope="personal",  # 个人知识库：owner 为业务用户本人，project_id 为空
        zone="material",
        asset_type="methodology",
        owner_user_id=USER_CONSULTANT,
        visibility="confidential",
        confidentiality_level="L2",
        ai_access_level="A1",
        asset_status="active",
    )
    version = KnowledgeAssetVersion(
        version_no="v1", version_status="active", created_by=USER_CONSULTANT
    )
    asset.versions.append(version)

    summary = KnowledgeAssetSummary(summary_type="one_liner", content="一句话摘要")
    summary.version = version
    asset.summaries.append(summary)

    tag = KnowledgeAssetTag(tag_name="数字化转型")
    asset.tags.append(tag)

    db_session.add(asset)
    await db_session.commit()

    # 重新查询并预加载关系，验证容器关系成立。
    stmt = (
        select(KnowledgeAsset)
        .options(
            selectinload(KnowledgeAsset.versions),
            selectinload(KnowledgeAsset.summaries),
            selectinload(KnowledgeAsset.tags),
        )
        .where(KnowledgeAsset.id == asset.id)
    )
    loaded = (await db_session.execute(stmt)).scalar_one()
    assert loaded.scope == "personal"
    assert loaded.project_id is None
    assert len(loaded.versions) == 1
    assert len(loaded.summaries) == 1
    assert loaded.summaries[0].summary_type == "one_liner"
    assert [t.tag_name for t in loaded.tags] == ["数字化转型"]


async def test_create_project_asset_with_project_id(db_session):
    """project 资产应携带 project_id（scope=project 时 project_id 必填的业务语义）。"""
    asset = await _make_asset(db_session, scope="project", project_id=PROJECT_ALPHA)
    assert asset.scope == "project"
    assert asset.project_id == PROJECT_ALPHA


async def test_version_no_unique_per_asset(db_session):
    """同一 asset 下 version_no 唯一约束生效。"""
    asset = await _make_asset(db_session, scope="company")
    db_session.add(
        KnowledgeAssetVersion(
            asset_id=asset.id, version_no="v1", version_status="active",
            created_by=USER_CONSULTANT,
        )
    )
    await db_session.commit()
    db_session.add(
        KnowledgeAssetVersion(
            asset_id=asset.id, version_no="v1", version_status="draft",
            created_by=USER_CONSULTANT,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_only_one_active_version_per_asset(db_session):
    """同一 asset 至多一个 active 版本（部分唯一索引在 SQLite 上同样生效）。"""
    asset = await _make_asset(db_session, scope="company")
    # 先取出 asset_id 到本地变量：rollback 后 ORM 对象属性会过期，
    # 在异步会话里再次访问会触发懒加载 IO 而报 MissingGreenlet。
    asset_id = asset.id

    db_session.add(
        KnowledgeAssetVersion(
            asset_id=asset_id, version_no="v1", version_status="active",
            created_by=USER_CONSULTANT,
        )
    )
    await db_session.commit()
    # 第二个 active 版本应触发部分唯一索引冲突。
    db_session.add(
        KnowledgeAssetVersion(
            asset_id=asset_id, version_no="v2", version_status="active",
            created_by=USER_CONSULTANT,
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()

    # 但 active + 非 active（如 draft）应被允许。
    db_session.add(
        KnowledgeAssetVersion(
            asset_id=asset_id, version_no="v3", version_status="draft",
            created_by=USER_CONSULTANT,
        )
    )
    await db_session.commit()
    count = await db_session.scalar(
        select(func.count())
        .select_from(KnowledgeAssetVersion)
        .where(KnowledgeAssetVersion.asset_id == asset_id)
    )
    assert count == 2


async def test_chunk_index_unique_per_version(db_session):
    """同一 version 下 chunk_index 唯一约束生效。"""
    asset = await _make_asset(db_session, scope="company")
    version = KnowledgeAssetVersion(
        asset_id=asset.id, version_no="v1", version_status="active",
        created_by=USER_CONSULTANT,
    )
    db_session.add(version)
    await db_session.commit()

    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id, version_id=version.id, chunk_index=0,
            chunk_type="paragraph", content_text="第一段", chunk_status="active",
        )
    )
    await db_session.commit()
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id, version_id=version.id, chunk_index=0,
            chunk_type="paragraph", content_text="重复 index", chunk_status="active",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_file_variant_unique_per_asset_version(db_session):
    """同一 asset/version/file_variant 唯一约束生效。"""
    asset = await _make_asset(db_session, scope="company")
    version = KnowledgeAssetVersion(
        asset_id=asset.id, version_no="v1", version_status="active",
        created_by=USER_CONSULTANT,
    )
    db_session.add(version)
    await db_session.commit()

    db_session.add(
        KnowledgeAssetFileObject(
            asset_id=asset.id, version_id=version.id, file_variant="original",
            file_name="a.pdf", file_mime_type="application/pdf",
            storage_ref="internal://obj/a", confidentiality_level="L2",
        )
    )
    await db_session.commit()
    db_session.add(
        KnowledgeAssetFileObject(
            asset_id=asset.id, version_id=version.id, file_variant="original",
            file_name="dup.pdf", file_mime_type="application/pdf",
            storage_ref="internal://obj/dup", confidentiality_level="L2",
        )
    )
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_tag_name_unique_per_asset(db_session):
    """同一 asset/tag_name 唯一约束生效。"""
    asset = await _make_asset(db_session, scope="company")
    db_session.add(KnowledgeAssetTag(asset_id=asset.id, tag_name="供应链"))
    await db_session.commit()
    db_session.add(KnowledgeAssetTag(asset_id=asset.id, tag_name="供应链"))
    with pytest.raises(IntegrityError):
        await db_session.commit()


async def test_self_references(db_session):
    """自引用可表达：source_asset_id / supersedes_version_id / replaced_by_chunk_id。"""
    # source_asset_id：新资产指向来源个人资产。
    origin = await _make_asset(db_session, scope="personal")
    derived = KnowledgeAsset(
        title="项目化资产",
        scope="project",
        zone="material",
        asset_type="methodology",
        owner_user_id=USER_CONSULTANT,
        project_id=PROJECT_ALPHA,
        source_asset_id=origin.id,
        visibility="project_only",
        confidentiality_level="L2",
        ai_access_level="A1",
        asset_status="active",
    )
    db_session.add(derived)
    await db_session.commit()
    assert derived.source_asset_id == origin.id

    # supersedes_version_id：新版本替代旧版本。
    v_old = KnowledgeAssetVersion(
        asset_id=derived.id, version_no="v1", version_status="superseded",
        created_by=USER_CONSULTANT,
    )
    db_session.add(v_old)
    await db_session.commit()
    v_new = KnowledgeAssetVersion(
        asset_id=derived.id, version_no="v2", version_status="active",
        created_by=USER_CONSULTANT, supersedes_version_id=v_old.id,
    )
    db_session.add(v_new)
    await db_session.commit()
    assert v_new.supersedes_version_id == v_old.id

    # replaced_by_chunk_id：旧 chunk 被新 chunk 替代。
    c_new = KnowledgeAssetChunk(
        asset_id=derived.id, version_id=v_new.id, chunk_index=0,
        chunk_type="paragraph", content_text="新内容", chunk_status="active",
    )
    db_session.add(c_new)
    await db_session.commit()
    c_old = KnowledgeAssetChunk(
        asset_id=derived.id, version_id=v_new.id, chunk_index=1,
        chunk_type="paragraph", content_text="旧内容", chunk_status="superseded",
        replaced_by_chunk_id=c_new.id,
    )
    db_session.add(c_old)
    await db_session.commit()
    assert c_old.replaced_by_chunk_id == c_new.id


async def test_invalid_chunk_carries_invalidation_metadata(db_session):
    """业务语义：chunk 失效时应带 invalidated_by / invalidated_at（此处以正向构造表达）。"""
    from datetime import datetime, timezone

    asset = await _make_asset(db_session, scope="company")
    version = KnowledgeAssetVersion(
        asset_id=asset.id, version_no="v1", version_status="active",
        created_by=USER_CONSULTANT,
    )
    db_session.add(version)
    await db_session.commit()

    chunk = KnowledgeAssetChunk(
        asset_id=asset.id, version_id=version.id, chunk_index=0,
        chunk_type="policy_article", content_text="旧政策条款",
        chunk_status="invalid", invalid_reason="政策已更新",
        invalidated_by=USER_BOSS, invalidated_at=datetime.now(timezone.utc),
    )
    db_session.add(chunk)
    await db_session.commit()

    count = await db_session.scalar(
        select(func.count())
        .select_from(KnowledgeAssetChunk)
        .where(KnowledgeAssetChunk.chunk_status == "invalid")
    )
    assert count == 1
    assert chunk.invalidated_by == USER_BOSS
    assert chunk.invalidated_at is not None


def test_storage_ref_not_exposed_in_any_schema():
    """`storage_ref` 是内部字段，不得出现在任何 Pydantic 响应 schema 中。

    本阶段未创建知识相关 response schema；扫描 app/schemas 下所有源码，
    确保没有任何 schema 文件引用 storage_ref。
    """
    pkg_dir = Path(schemas_pkg.__file__).parent
    for py in pkg_dir.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "storage_ref" not in text, f"{py.name} 不应出现 storage_ref"
