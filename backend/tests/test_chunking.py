"""治理文本切块（D1 v1.3 阶段3）单测。"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.models.knowledge import KnowledgeAssetChunk
from app.services.chunking import CHUNK_CHAR_LIMIT, chunk_governance_text, rebuild_version_chunks


def test_heading_split_tracks_section():
    chunks = chunk_governance_text("# 第一章\n内容A\n## 小节\n内容B")
    assert len(chunks) == 2
    assert chunks[0].source_section == "第一章"
    assert "内容A" in chunks[0].content
    assert chunks[1].source_section == "小节"
    assert "内容B" in chunks[1].content


def test_page_marker_sets_source_page_and_stays_out_of_content():
    chunks = chunk_governance_text("{{page:1}}\n第一页内容\n{{page:2}}\n第二页内容")
    assert len(chunks) == 2
    assert chunks[0].source_page == 1
    assert chunks[1].source_page == 2
    assert "{{page:" not in chunks[0].content
    assert "{{page:" not in chunks[1].content


def test_pptx_slide_marker_parsed_as_page():
    chunks = chunk_governance_text("[幻灯片 3]\n标题\n正文")
    assert chunks[0].source_page == 3


def test_long_block_falls_back_to_char_limit():
    chunks = chunk_governance_text("字" * (CHUNK_CHAR_LIMIT * 2 + 10))
    assert len(chunks) == 2
    assert len(chunks[0].content) >= CHUNK_CHAR_LIMIT


async def test_rebuild_version_chunks_replaces_rows(db_session):
    asset_id, version_id = uuid.uuid4(), uuid.uuid4()
    await rebuild_version_chunks(
        db_session,
        asset_id=asset_id,
        version_id=version_id,
        governance_text="# 章节\n内容",
    )
    rows = list(
        (
            await db_session.execute(
                select(KnowledgeAssetChunk).where(KnowledgeAssetChunk.version_id == version_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].source_section == "章节"
    assert rows[0].chunk_type == "governance_text"
    assert rows[0].chunk_status == "active"

    # 重建替换旧行，不重复累积。
    await rebuild_version_chunks(
        db_session,
        asset_id=asset_id,
        version_id=version_id,
        governance_text="# 新章节\n新内容",
    )
    rows2 = list(
        (
            await db_session.execute(
                select(KnowledgeAssetChunk).where(KnowledgeAssetChunk.version_id == version_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows2) == 1
    assert rows2[0].content_text == "# 新章节\n新内容"
