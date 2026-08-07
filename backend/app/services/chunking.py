"""治理文本切块（D1 v1.3 阶段3）。

把 verbatim 治理文本切成 KAP 侧 chunk，并记录来源页码 / 章节，落
`knowledge_asset_chunks`。切块策略：按标题（# / ## / ###）切，超长按
`CHUNK_CHAR_LIMIT` 兜底；`{{page:N}}`（PDF 提取插入）与 `[幻灯片 N]`（PPT 旧格式）
解析为 `source_page`。

说明：这张表是**定位索引**（命中 → 资产/版本/页码/章节），不是召回索引——召回仍由
WeKnora 负责。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeAssetChunk

# 单块字符上限（与 WeKnora KB 级 chunkSize 对齐的量级）。
CHUNK_CHAR_LIMIT = 512

_PAGE_RE = re.compile(r"\{\{page:(\d+)\}\}|^\[幻灯片\s*(\d+)\]", re.MULTILINE)
_HEADING_RE = re.compile(r"^(#{1,3})\s+(.+)$")


@dataclass(frozen=True)
class ChunkDraft:
    content: str
    source_page: int | None
    source_section: str | None


def chunk_governance_text(text: str) -> list[ChunkDraft]:
    """按标题 + 页码切块，返回有序块（含定位元数据）。"""
    lines = text.splitlines()
    chunks: list[ChunkDraft] = []
    buffer: list[str] = []
    page: int | None = None
    section: str | None = None

    def emit(content: str) -> None:
        content = content.strip()
        if content:
            chunks.append(ChunkDraft(content=content, source_page=page, source_section=section))

    def flush() -> None:
        nonlocal buffer
        emit("\n".join(buffer))
        buffer = []

    for line in lines:
        page_match = _PAGE_RE.search(line)
        if page_match:
            new_page = int(page_match.group(1) or page_match.group(2))
            rest = _PAGE_RE.sub("", line).strip()
            if not rest:
                flush()  # 先把上一页内容以旧页码落块
                page = new_page
                continue  # 纯页码标记行不进正文
            page = new_page
            line = rest
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            section = heading.group(2).strip()
            buffer.append(line)
            continue
        if len(line) >= CHUNK_CHAR_LIMIT:
            # 超长单行（如巨大表格单元格 / 压缩文本）按上限拆块。
            flush()
            pieces: list[str] = []
            start = 0
            while start < len(line):
                end = min(start + CHUNK_CHAR_LIMIT, len(line))
                pieces.append(line[start:end])
                start = end
            if len(pieces) > 1 and len(pieces[-1]) < 64:
                pieces[-2] += pieces[-1]
                pieces.pop()
            for piece in pieces:
                emit(piece)
            continue
        buffer.append(line)
        if sum(len(item) for item in buffer) >= CHUNK_CHAR_LIMIT:
            flush()
    flush()
    return chunks


async def rebuild_version_chunks(
    session: AsyncSession,
    *,
    asset_id,
    version_id,
    governance_text: str,
) -> None:
    """版本级重建 chunk：先删该版本旧行，再按治理文本切块写入（同事务）。"""
    await session.execute(
        delete(KnowledgeAssetChunk).where(KnowledgeAssetChunk.version_id == version_id)
    )
    for index, draft in enumerate(chunk_governance_text(governance_text)):
        session.add(
            KnowledgeAssetChunk(
                asset_id=asset_id,
                version_id=version_id,
                chunk_index=index,
                chunk_type="governance_text",
                content_text=draft.content,
                source_page=draft.source_page,
                source_section=draft.source_section,
                token_count=max(1, len(draft.content) // 4),
                chunk_hash=hashlib.sha256(draft.content.encode("utf-8")).hexdigest(),
                chunk_status="active",
            )
        )
