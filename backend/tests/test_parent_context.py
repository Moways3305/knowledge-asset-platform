"""D1 阶段4：子块召回 → 父文件全文给 Agent（Small-to-Big）函数级测试。"""

from __future__ import annotations

import uuid

from app.models.knowledge import (
    KnowledgeAsset,
    KnowledgeAssetChunk,
    KnowledgeAssetSummary,
    KnowledgeAssetVersion,
)
from app.schemas.permission import (
    AccessLayer,
    DeniedReason,
    EffectiveAccessSource,
    PermissionDecision,
)
from app.services import retrieval


def _decision(allowed: bool) -> PermissionDecision:
    return PermissionDecision(
        allowed=allowed,
        requested_layer=AccessLayer.original,
        allowed_layer=AccessLayer.original if allowed else AccessLayer.summary,
        denied_reason=DeniedReason.allowed if allowed else DeniedReason.original_requires_request,
        effective_access_source=EffectiveAccessSource.system_rule
        if allowed
        else EffectiveAccessSource.none,
        audit_required=False,
        strong_audit_required=False,
    )


def _asset(*, title: str = "测试资产", conf: str = "L1") -> KnowledgeAsset:
    asset = KnowledgeAsset(
        id=uuid.uuid4(),
        title=title,
        scope="project",
        zone="material",
        asset_type="document",
        owner_user_id=uuid.uuid4(),
        confidentiality_level=conf,
        ai_access_level="A1",
        asset_status="active",
        visibility="project_only",
    )
    asset.summaries = []
    asset.tags = []
    return asset


def _version(asset: KnowledgeAsset) -> KnowledgeAssetVersion:
    return KnowledgeAssetVersion(
        id=uuid.uuid4(),
        asset_id=asset.id,
        version_no="v1",
        version_status="active",
        created_by=uuid.uuid4(),
        index_status="indexed",
        weknora_doc_id=f"wk-doc-{asset.id}",
        weknora_kb_id="wk-kb",
    )


def _recalled(
    asset: KnowledgeAsset,
    version: KnowledgeAssetVersion,
    *,
    original_allowed: bool = True,
    summary_allowed: bool = True,
) -> retrieval.RecalledAsset:
    return retrieval.RecalledAsset(
        asset=asset,
        version=version,
        score=0.9,
        matched_chunks=[
            {
                "knowledge_id": version.weknora_doc_id,
                "seq": 0,
                "chunk_index": 0,
                "content": "命中片段内容",
            }
        ],
        discovery=_decision(True),
        summary=_decision(summary_allowed),
        original=_decision(original_allowed),
    )


class FakeDesens:
    """记录调用并可模拟擦洗失败。"""

    def __init__(self, result: str | None = "已擦洗全文"):
        self.result = result
        self.calls: list[str] = []

    async def scrub(self, text: str, *, trace_id: str | None = None) -> str | None:
        self.calls.append(text)
        return self.result


class CaptureLLM:
    """捕获喂给 LLM 的消息，固定返回答案。"""

    def __init__(self) -> None:
        self.messages: list[dict] | None = None

    async def chat_completion(
        self,
        messages,
        *,
        temperature: float = 0.2,
        model: str | None = None,
        json_object: bool = False,
        trace_id: str | None = None,
    ) -> str:
        self.messages = messages
        return "【答案】"


def test_join_parent_document_rebuilds_page_markers():
    chunks = [
        KnowledgeAssetChunk(
            asset_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            chunk_index=0,
            chunk_type="governance_text",
            content_text="第一章 摘要",
            source_page=1,
            source_section="第一章 摘要",
            chunk_status="active",
        ),
        KnowledgeAssetChunk(
            asset_id=uuid.uuid4(),
            version_id=uuid.uuid4(),
            chunk_index=1,
            chunk_type="governance_text",
            content_text="第二页正文内容",
            source_page=2,
            chunk_status="active",
        ),
    ]
    joined = retrieval._join_parent_document(chunks)
    assert "[第 1 页]" in joined
    assert "[第 2 页]" in joined
    assert joined.index("[第 1 页]") < joined.index("第一章 摘要")
    assert joined.index("[第 2 页]") < joined.index("第二页正文内容")


async def test_gather_parent_context_returns_full_text(db_session):
    asset = _asset()
    version = _version(asset)
    db_session.add(asset)
    db_session.add(version)
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=0,
            chunk_type="governance_text",
            content_text="第一章 需求分析",
            source_page=1,
            source_section="第一章 需求分析",
            chunk_status="active",
        )
    )
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=1,
            chunk_type="governance_text",
            content_text="第二章 实施方案",
            source_page=2,
            source_section="第二章 实施方案",
            chunk_status="active",
        )
    )
    await db_session.commit()

    desens = FakeDesens()
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version)],
        desens,
        trace_id="trc-parent",
    )
    assert len(evidences) == 1
    ev = evidences[0]
    assert ev.used_layer == "original"
    assert ev.seq is None  # 文件级证据
    assert ev.asset.id == asset.id
    assert "第一章 需求分析" in ev.snippet
    assert "第二章 实施方案" in ev.snippet
    assert "[第 2 页]" in ev.snippet
    # L1/L2 直通，不触发 LLM 擦洗。
    assert desens.calls == []


async def test_gather_parent_context_scrubs_high_confidentiality(db_session):
    asset = _asset(conf="L3")
    version = _version(asset)
    db_session.add(asset)
    db_session.add(version)
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=0,
            chunk_type="governance_text",
            content_text="L3 敏感方案全文",
            source_page=1,
            chunk_status="active",
        )
    )
    await db_session.commit()

    desens = FakeDesens(result="擦洗后的安全全文")
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version)],
        desens,
        trace_id="trc-parent",
    )
    assert desens.calls, "L3 全文必须走 LLM 擦洗"
    assert len(evidences) == 1
    assert "擦洗后的安全全文" in evidences[0].snippet
    assert "L3 敏感方案全文" not in evidences[0].snippet


async def test_gather_parent_context_scrub_failure_downgrades(db_session):
    asset = _asset(conf="L5")
    version = _version(asset)
    db_session.add(asset)
    db_session.add(version)
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=0,
            chunk_type="governance_text",
            content_text="L5 原文",
            source_page=1,
            chunk_status="active",
        )
    )
    await db_session.commit()

    # 擦洗不可用 → 该篇不进父上下文（conservative），无摘要则最终无证据。
    desens = FakeDesens(result=None)
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version)],
        desens,
        trace_id="trc-parent",
    )
    assert evidences == []


async def test_gather_parent_context_no_chunks_falls_back(db_session):
    """存量资产（阶段3 部署前无 chunk 注册表）回退命中片段，问答不因阶段4变空。"""
    asset = _asset()
    version = _version(asset)
    db_session.add(asset)
    db_session.add(version)
    await db_session.commit()

    desens = FakeDesens()
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version)],
        desens,
        trace_id="trc-parent",
    )
    assert len(evidences) == 1
    assert "命中片段内容" in evidences[0].snippet
    assert evidences[0].seq == 0  # 回退仍为片段级证据


async def test_gather_parent_context_respects_doc_limit(db_session):
    assets = [_asset(title=f"资产{i}") for i in range(3)]
    recalled = []
    for asset in assets:
        version = _version(asset)
        db_session.add(asset)
        db_session.add(version)
        db_session.add(
            KnowledgeAssetChunk(
                asset_id=asset.id,
                version_id=version.id,
                chunk_index=0,
                chunk_type="governance_text",
                content_text=f"全文内容-{asset.title}",
                source_page=1,
                chunk_status="active",
            )
        )
        recalled.append(_recalled(asset, version))
    await db_session.commit()

    desens = FakeDesens()
    evidences = await retrieval.gather_parent_context(
        db_session,
        recalled,
        desens,
        trace_id="trc-parent",
        parent_doc_limit=1,
    )
    # 只有第一篇走全文；其余资产有 chunk 但超 N，仍回退片段证据。
    full_texts = [e for e in evidences if e.seq is None]
    assert len(full_texts) == 1
    assert "全文内容-资产0" in full_texts[0].snippet
    assert len(evidences) == 3  # 每资产至少一条（全文或兜底片段）


async def test_gather_parent_context_truncates_head(db_session):
    asset = _asset()
    version = _version(asset)
    db_session.add(asset)
    db_session.add(version)
    db_session.add(
        KnowledgeAssetChunk(
            asset_id=asset.id,
            version_id=version.id,
            chunk_index=0,
            chunk_type="governance_text",
            content_text="A" * 300,
            source_page=1,
            chunk_status="active",
        )
    )
    await db_session.commit()

    desens = FakeDesens()
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version)],
        desens,
        trace_id="trc-parent",
        parent_doc_char_limit=100,
    )
    assert len(evidences) == 1
    assert "[内容过长已截断" in evidences[0].snippet
    assert len(evidences[0].snippet) < 300


async def test_gather_parent_context_no_original_permission_summary_fallback(db_session):
    asset = _asset()
    version = _version(asset)
    asset.summaries = [
        KnowledgeAssetSummary(
            asset_id=asset.id,
            version_id=version.id,
            summary_type="detailed",
            content="安全业务摘要",
        )
    ]
    db_session.add(asset)
    db_session.add(version)
    await db_session.commit()

    desens = FakeDesens()
    evidences = await retrieval.gather_parent_context(
        db_session,
        [_recalled(asset, version, original_allowed=False)],
        desens,
        trace_id="trc-parent",
    )
    assert len(evidences) == 1
    assert evidences[0].used_layer == "summary"
    assert "安全业务摘要" in evidences[0].snippet


async def test_synthesize_answer_uses_full_text_blocks():
    asset = _asset(title="实施方案")
    llm = CaptureLLM()
    evidence = retrieval.Evidence(
        asset=asset,
        used_layer="original",
        snippet="第一章 全文内容",
        seq=None,
        weknora_chunk_ref=None,
    )
    answer = await retrieval.synthesize_answer(
        llm, "方案要点是什么", [evidence], trace_id="trc-synth"
    )
    assert answer == "【答案】"
    assert llm.messages is not None
    user_content = llm.messages[1]["content"]
    assert "《实施方案》" in user_content
    assert "保密 L1" in user_content
    assert "第一章 全文内容" in user_content
    assert "交叉综合" in llm.messages[0]["content"]
