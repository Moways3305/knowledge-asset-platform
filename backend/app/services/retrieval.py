"""两阶段检索编排服务。

统一把"查询 → WeKnora 召回 → 映射回业务资产 →
集中权限 `decide()` 复核 → 阶段1卡片 / 阶段2脱敏原文 / 问答证据"收口到这里。

强约束（头号安全闸）：
- **检索最大化用 WeKnora**（hybrid/knowledge-search），不自造向量检索。
- chunk → 资产映射：WeKnora `knowledge_id` ↔ 业务库 `knowledge_asset_versions.weknora_doc_id`。
  召回到**无映射 / 非 active 版本 / 非 active 资产**的知识一律**丢弃**，不透出无主内容。
- 三道过滤（阶段2原文）：①KB-scope 预过滤（只搜调用人可访问 KB + knowledge_ids 限定）
  ②逐 chunk `decide()` 复核 ③输出脱敏。**无权一律只给卡片，永不给原文 chunk**——
  权限闸是确定性主控制，LLM 脱敏是其上的内容擦洗层。
- 响应/服务对外**绝不**携带 weknora kb/doc/chunk id、storage_ref、api_key、未脱敏原文。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.identity import Project, User
from app.models.knowledge import KnowledgeAsset, KnowledgeAssetChunk, KnowledgeAssetVersion
from app.models.weknora import WeknoraKbMapping
from app.schemas.enums import (
    AssetStatus,
    ConfidentialityLevel,
    KnowledgeScope,
    VersionStatus,
)
from app.schemas.permission import (
    AccessChannel,
    AccessLayer,
    CallerContext,
    EffectiveAccessSource,
    PermissionDecision,
)
from app.services import original_access
from app.services.desensitization import OutputDesensitizer
from app.services.llm_client import LLMClient, LLMError, NullLLMClient
from app.services.permission import decide
from app.services.permission_rules import load_access_policy
from app.services.weknora_client import NullWeKnoraClient, WeKnoraClient

# 需要输出脱敏的保密级别（返回原文/片段前必须实体脱敏）。
_logger = logging.getLogger(__name__)

_DESENSITIZE_LEVELS = {
    ConfidentialityLevel.L3.value,
    ConfidentialityLevel.L4.value,
    ConfidentialityLevel.L5.value,
}
_REDACTED_LEVELS = {ConfidentialityLevel.L3.value, ConfidentialityLevel.L4.value}
_ACTIVE_ASSET = AssetStatus.active.value
_ACTIVE_VERSION = VersionStatus.active.value
# 只有底座索引成功（index_status=indexed）的 version 才可参与语义召回 / 原文 chunk 取件
# ：index_failed/not_indexed/skipped 即使残留 server-only
# weknora_doc_id（如 reparse 删旧 doc 失败 + 重传失败），其底座旧 doc 也不得被平台当作有效索引使用。
_INDEXED_STATUS = "indexed"

# 召回与证据规模上限（控成本/时延）。
_RECALL_TOP_K = 20
_MAX_EVIDENCE_ASSETS = 6
_MAX_CHUNKS_PER_ASSET = 2
# D1 阶段4：父文件全文给 Agent 时，每篇最多几篇 / 单篇字符上限（默认读配置，测试可覆盖）。
_DEFAULT_PARENT_DOC_LIMIT = 3
_DEFAULT_PARENT_DOC_CHAR_LIMIT = 16000


def needs_desensitization(asset: KnowledgeAsset) -> bool:
    """返回原文/片段前是否必须做实体脱敏（L3/L4/L5 必脱敏；L1/L2 内部一般资料不强制）。"""
    return asset.confidentiality_level in _DESENSITIZE_LEVELS


@dataclass
class RecalledAsset:
    """一条去重到资产级的召回结果（server-only，含原始 chunk，不直接外泄）。"""

    asset: KnowledgeAsset
    version: KnowledgeAssetVersion
    score: float
    # 该资产命中的 WeKnora 原始 chunk（含未脱敏 content）——仅服务端持有，按权限+脱敏后才外泄。
    matched_chunks: list[dict] = field(default_factory=list)
    discovery: PermissionDecision | None = None
    summary: PermissionDecision | None = None
    original: PermissionDecision | None = None

    @property
    def can_view_original(self) -> bool:
        return bool(self.original and self.original.allowed)


@dataclass
class Evidence:
    """喂给 LLM 自拼答案的一条放行证据（已按权限取层、已脱敏）。"""

    asset: KnowledgeAsset
    used_layer: str  # original / summary
    snippet: str
    seq: int | None
    weknora_chunk_ref: str | None  # server-only，绝不外泄


# ---------------------------------------------------------------------------
# KB 解析（scope → 可检索 KB 集）
# ---------------------------------------------------------------------------
async def _kb_ids_for(
    session: AsyncSession, *, scope: str, owner_user_id=None, project_ids=None
) -> list[str]:
    stmt = select(WeknoraKbMapping.weknora_kb_id).where(
        WeknoraKbMapping.scope == scope, WeknoraKbMapping.status == "active"
    )
    if scope == KnowledgeScope.personal.value:
        stmt = stmt.where(WeknoraKbMapping.owner_user_id == owner_user_id)
    elif scope == KnowledgeScope.project.value:
        if project_ids is not None:
            if not project_ids:
                return []
            stmt = stmt.where(WeknoraKbMapping.project_id.in_(list(project_ids)))
    return [r[0] for r in (await session.execute(stmt)).all()]


async def resolve_searchable_kbs(
    session: AsyncSession, caller: CallerContext, scope: str | None
) -> list[str]:
    """按 scope + 调用人可访问范围确定可检索 KB 集（scope 路由预过滤，三道过滤第①道）。

    - personal：仅本人个人 KB（且需为业务用户）。
    - project：全局知识检索可路由到所有项目 KB；召回后仍逐资产执行 `decide()`，
      非成员 L1-L4 只使用已保存摘要，L5 丢弃。
    - company：公司 KB。
    - all / None：以上并集。
    """
    want_all = scope in (None, "all")
    kbs: set[str] = set()
    if (want_all or scope == KnowledgeScope.personal.value) and caller.is_business_user:
        kbs.update(
            await _kb_ids_for(
                session, scope=KnowledgeScope.personal.value, owner_user_id=caller.user_id
            )
        )
    if want_all or scope == KnowledgeScope.project.value:
        kbs.update(await _kb_ids_for(session, scope=KnowledgeScope.project.value))
    if want_all or scope == KnowledgeScope.company.value:
        kbs.update(await _kb_ids_for(session, scope=KnowledgeScope.company.value))
    return list(kbs)


async def resolve_project_kbs(session: AsyncSession, project_id: uuid.UUID) -> list[str]:
    """单个项目的 KB 集（项目 Q&A 用，限定到该项目）。"""
    return await _kb_ids_for(session, scope=KnowledgeScope.project.value, project_ids=[project_id])


# ---------------------------------------------------------------------------
# 召回：WeKnora chunk → 资产映射 → 去重 → 逐资产 decide()
# ---------------------------------------------------------------------------
async def recall_assets(
    session: AsyncSession,
    caller: CallerContext,
    weknora: WeKnoraClient | NullWeKnoraClient,
    *,
    query: str,
    kb_ids: list[str],
    channel: AccessChannel,
    knowledge_ids: list[str] | None = None,
    trace_id: str | None = None,
) -> list[RecalledAsset]:
    """召回并映射到资产级（去重取最高 score），逐资产三层 `decide()`。

    只返回**发现层放行**的资产（L5/他人个人等被 decide(discovery) 自然过滤）；
    archived/superseded/非 active 版本/孤儿 knowledge 一律丢弃。按 score 降序。
    """
    if not kb_ids:
        return []
    chunks = await weknora.search(
        query=query,
        kb_ids=kb_ids,
        knowledge_ids=knowledge_ids,
        top_k=_RECALL_TOP_K,
        trace_id=trace_id,
    )
    if not chunks:
        return []

    # 收集命中的 knowledge_id（= 业务库 weknora_doc_id），批量映射回 active 版本/资产。
    doc_ids = {c["knowledge_id"] for c in chunks if c.get("knowledge_id")}
    if not doc_ids:
        return []
    versions = list(
        (
            await session.execute(
                select(KnowledgeAssetVersion)
                .where(KnowledgeAssetVersion.weknora_doc_id.in_(doc_ids))
                .where(KnowledgeAssetVersion.version_status == _ACTIVE_VERSION)
                .where(
                    or_(
                        KnowledgeAssetVersion.directory_key.is_(None),
                        KnowledgeAssetVersion.directory_key != "personal.pending",
                    )
                )
                # residual：仅索引成功的 version 可被召回映射；index_failed 等残留旧 doc 丢弃。
                .where(KnowledgeAssetVersion.index_status == _INDEXED_STATUS)
            )
        )
        .scalars()
        .all()
    )
    doc_to_version = {v.weknora_doc_id: v for v in versions}
    asset_ids = {v.asset_id for v in versions}
    if not asset_ids:
        return []
    assets = list(
        (
            await session.execute(
                select(KnowledgeAsset)
                .where(KnowledgeAsset.id.in_(asset_ids))
                .where(KnowledgeAsset.asset_status == _ACTIVE_ASSET)  # 丢弃 archived/deprecated
                .options(
                    selectinload(KnowledgeAsset.summaries),
                    selectinload(KnowledgeAsset.tags),
                )
            )
        )
        .scalars()
        .all()
    )
    asset_by_id = {a.id: a for a in assets}

    # 去重到资产级：取最高 score；同资产多 chunk 全部留作证据（阶段2/问答按 chunk 保留）。
    recalled: dict[uuid.UUID, RecalledAsset] = {}
    for c in chunks:
        version = doc_to_version.get(c["knowledge_id"])
        if version is None:  # 孤儿/非 active 版本 → 丢弃，不透出无主内容
            continue
        asset = asset_by_id.get(version.asset_id)
        if asset is None:  # 资产非 active → 丢弃
            continue
        score = float(c.get("score") or 0.0)
        entry = recalled.get(asset.id)
        if entry is None:
            entry = RecalledAsset(asset=asset, version=version, score=score)
            recalled[asset.id] = entry
        entry.matched_chunks.append(c)
        entry.score = max(entry.score, score)

    # 批量取调用人对召回资产的 active 原文授权，原文层判断统一叠加。
    granted_ids = await original_access.active_grant_asset_ids(session, caller, recalled.keys())
    # L1/L2 原文默认放行由运行时 policy 决定。
    policy = await load_access_policy(session)

    # 逐资产三层判断（discovery 被拒的资产连卡片都不出）。
    out: list[RecalledAsset] = []
    for entry in recalled.values():
        d = decide(caller, entry.asset, AccessLayer.discovery, channel=channel, policy=policy)
        if not d.allowed:
            continue
        has_grant = entry.asset.id in granted_ids
        entry.discovery = d
        entry.summary = decide(
            caller,
            entry.asset,
            AccessLayer.summary,
            channel=channel,
            has_original_grant=has_grant,
            policy=policy,
        )
        entry.original = decide(
            caller,
            entry.asset,
            AccessLayer.original,
            channel=channel,
            has_original_grant=has_grant,
            policy=policy,
        )
        out.append(entry)

    out.sort(key=lambda r: r.score, reverse=True)
    # 仅记召回数量；绝不记 query / chunk 正文 / kb·doc id。
    _logger.info("retrieval_recall", extra={"result_count": len(out)})
    return out


# ---------------------------------------------------------------------------
# 阶段1卡片
# ---------------------------------------------------------------------------
def _summary_map(asset: KnowledgeAsset) -> dict[str, str | None]:
    return {s.summary_type: s.content for s in asset.summaries}


def _card_summary_fields(
    asset: KnowledgeAsset, summary_allowed: bool
) -> tuple[str | None, str | None, list[str]]:
    """卡片三层摘要字段：one_liner / detailed / key_points。

    L3/L4 取脱敏摘要（redacted/safe），key_points 置空（原始要点未脱敏，不外泄）。
    无摘要层权限 → 全空（卡片只剩发现层元数据）。
    """
    if not summary_allowed:
        return None, None, []
    smap = _summary_map(asset)
    if asset.confidentiality_level in _REDACTED_LEVELS:
        safe = smap.get("redacted_summary") or smap.get("safe_summary")
        return safe, safe, []
    kp_raw = smap.get("key_points")
    key_points = [ln.strip() for ln in kp_raw.split("\n") if ln.strip()] if kp_raw else []
    return smap.get("one_liner"), smap.get("detailed"), key_points


async def load_card_aux(
    session: AsyncSession, assets: list[KnowledgeAsset]
) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, str]]:
    """批量加载卡片所需的项目名与联系人（owner/maintainer）姓名，避免 N+1。"""
    project_ids = {a.project_id for a in assets if a.project_id}
    user_ids = set()
    for a in assets:
        if a.owner_user_id:
            user_ids.add(a.owner_user_id)
        if a.maintainer_user_id:
            user_ids.add(a.maintainer_user_id)
    projects: dict[uuid.UUID, str] = {}
    users: dict[uuid.UUID, str] = {}
    if project_ids:
        projects = {
            r[0]: r[1]
            for r in (
                await session.execute(
                    select(Project.id, Project.name).where(Project.id.in_(project_ids))
                )
            ).all()
        }
    if user_ids:
        users = {
            r[0]: r[1]
            for r in (
                await session.execute(select(User.id, User.name).where(User.id.in_(user_ids)))
            ).all()
        }
    return projects, users


def build_card(
    recalled: RecalledAsset,
    projects: dict[uuid.UUID, str],
    users: dict[uuid.UUID, str],
) -> dict:
    """组装阶段1卡片（§6.1）。**绝不含**原文、kb/doc/chunk id、客户敏感实体。"""
    asset = recalled.asset
    summary_allowed = bool(recalled.summary and recalled.summary.allowed)
    one_liner, detailed, key_points = _card_summary_fields(asset, summary_allowed)
    cross_project_summary = (
        asset.scope == KnowledgeScope.project.value
        and recalled.discovery is not None
        and recalled.discovery.effective_access_source == EffectiveAccessSource.system_rule
    )
    return {
        "asset_id": asset.id,
        "title": asset.title,
        "asset_type": asset.asset_type,
        "scope": asset.scope,
        "zone": asset.zone,
        "confidentiality_level": asset.confidentiality_level,
        "phase": None if cross_project_summary else asset.lifecycle_phase_key,
        "tags": [t.tag_name for t in asset.tags],
        "one_liner": one_liner,
        "detailed": detailed,
        "key_points": key_points,
        "owner_name": (
            None
            if cross_project_summary
            else users.get(asset.owner_user_id)
            if asset.owner_user_id
            else None
        ),
        "maintainer_name": (
            None
            if cross_project_summary
            else users.get(asset.maintainer_user_id)
            if asset.maintainer_user_id
            else None
        ),
        "project_name": projects.get(asset.project_id) if asset.project_id else None,
        "updated_at": asset.updated_at,
        "version": recalled.version.version_no,
        "relevance_score": round(recalled.score, 6),
        "can_view_original": recalled.can_view_original,
    }


# ---------------------------------------------------------------------------
# 证据收集（问答自拼答案用）+ 输出脱敏
# ---------------------------------------------------------------------------
async def _scrub_chunk(
    desens: OutputDesensitizer, asset: KnowledgeAsset, content: str, *, trace_id: str | None
) -> str | None:
    """按保密级对原文 chunk 做输出脱敏。L1/L2 直接返回；L3/L4/L5 走 LLM 擦洗，
    脱敏不可用 → None（保守降级，调用方据此不返回该片段）。"""
    if not needs_desensitization(asset):
        return content
    return await desens.scrub(content, trace_id=trace_id)


async def gather_evidence(
    recalled: list[RecalledAsset],
    desens: OutputDesensitizer,
    *,
    trace_id: str | None,
) -> list[Evidence]:
    """收集放行证据：每个资产取其可达最高层级的安全内容。

    - original 放行：取命中 chunk（脱敏后；脱敏失败的片段丢弃）。
    - 仅 summary 放行：取业务库安全摘要（已脱敏，无需再过 LLM）。
    - 仅 discovery：无证据。
    引用片段也必须脱敏——L3/L4/L5 原文片段经 LLM 擦洗，summary 片段本就安全。
    """
    evidences: list[Evidence] = []
    for r in recalled[:_MAX_EVIDENCE_ASSETS]:
        if r.can_view_original and r.matched_chunks:
            taken = 0
            for c in r.matched_chunks:
                if taken >= _MAX_CHUNKS_PER_ASSET:
                    break
                content = (c.get("content") or "").strip()
                if not content:
                    continue
                scrubbed = await _scrub_chunk(desens, r.asset, content, trace_id=trace_id)
                if not scrubbed:  # 脱敏不可用 → 保守跳过（不外泄未脱敏原文）
                    continue
                ref = f"{c['knowledge_id']}#{c.get('chunk_index')}"
                evidences.append(
                    Evidence(
                        asset=r.asset,
                        used_layer=AccessLayer.original.value,
                        snippet=scrubbed[:600],
                        seq=c.get("seq"),
                        weknora_chunk_ref=ref,
                    )
                )
                taken += 1
        elif r.summary and r.summary.allowed:
            one_liner, detailed, _kp = _card_summary_fields(r.asset, True)
            snippet = (detailed or one_liner or "").strip()
            if snippet:
                evidences.append(
                    Evidence(
                        asset=r.asset,
                        used_layer=AccessLayer.summary.value,
                        snippet=snippet[:600],
                        seq=None,
                        weknora_chunk_ref=None,
                    )
                )
    return evidences


# ---------------------------------------------------------------------------
# D1 阶段4：子块召回 → 父文件全文给 Agent（Small-to-Big）
# ---------------------------------------------------------------------------
def _join_parent_document(chunks: list[KnowledgeAssetChunk]) -> str:
    """按 chunk_index 拼接治理文本全文，跨 source_page 变化重建 `[第 N 页]` 标记。

    阶段3 切块时纯页码标记行被丢弃，只保留在 chunk.source_page 元数据里；此处按
    页码变化重新插回标记，让 Agent 保持页码感知（逐页引用为后置项，仅作上下文提示）。
    """
    parts: list[str] = []
    last_page: int | None = None
    for chunk in chunks:
        if chunk.source_page is not None and chunk.source_page != last_page:
            parts.append(f"\n\n[第 {chunk.source_page} 页]\n")
            last_page = chunk.source_page
        parts.append(chunk.content_text)
    return "\n\n".join(parts).strip()


async def gather_parent_context(
    session: AsyncSession,
    recalled: list[RecalledAsset],
    desens: OutputDesensitizer,
    *,
    trace_id: str | None,
    parent_doc_limit: int | None = None,
    parent_doc_char_limit: int | None = None,
) -> list[Evidence]:
    """D1 阶段4：子块召回后按父文件聚合，取治理文本全文（≤N 篇）给 Agent。

    - 只取 `can_view_original` 的资产（权限闸不放松），按 recall score 取前 N 篇；
    - 全文来自 KAP 侧 `knowledge_asset_chunks` 注册表（阶段3 落库），不重提取原文件；
    - L1/L2 直通，L3/L4/L5 全文走 LLM 擦洗（擦洗失败 → 该篇降级不放行）；
    - 单篇超 `parent_doc_char_limit` 截头并打截断标记；
    - 未产出全文的资产（无原文权限 / 无 chunk 行 / 超 N 篇 / 擦洗失败）回退现有
      `gather_evidence` 的片段 / 摘要逻辑——存量老资产（阶段3 部署前）不会问答变空。
    """
    settings = get_settings()
    limit = settings.agent_parent_doc_limit if parent_doc_limit is None else parent_doc_limit
    char_limit = (
        settings.agent_parent_doc_char_limit
        if parent_doc_char_limit is None
        else parent_doc_char_limit
    )

    candidates = [r for r in recalled if r.can_view_original][: max(limit, 0)]
    if not candidates:
        return await gather_evidence(recalled, desens, trace_id=trace_id)

    version_ids = [r.version.id for r in candidates]
    rows = list(
        (
            await session.execute(
                select(KnowledgeAssetChunk)
                .where(KnowledgeAssetChunk.version_id.in_(version_ids))
                .order_by(
                    KnowledgeAssetChunk.version_id,
                    KnowledgeAssetChunk.chunk_index,
                )
            )
        )
        .scalars()
        .all()
    )
    chunks_by_version: dict[uuid.UUID, list[KnowledgeAssetChunk]] = {}
    for row in rows:
        chunks_by_version.setdefault(row.version_id, []).append(row)

    covered_ids: set[uuid.UUID] = set()
    parent_evidences: list[Evidence] = []
    for r in candidates:
        chunks = chunks_by_version.get(r.version.id) or []
        if not chunks:
            continue  # 存量资产无 chunk 注册表 → 走兜底
        full_text = _join_parent_document(chunks)
        if not full_text:
            continue
        truncated = len(full_text) > char_limit
        if truncated:
            full_text = full_text[:char_limit].rstrip() + (
                f"\n\n[内容过长已截断，仅展示前 {char_limit} 字符]"
            )
        scrubbed = await _scrub_chunk(desens, r.asset, full_text, trace_id=trace_id)
        if not scrubbed:
            continue  # 脱敏不可用 → 保守降级，该篇不进父上下文
        ref = None
        if r.matched_chunks:
            first = r.matched_chunks[0]
            ref = f"{first['knowledge_id']}#{first.get('chunk_index')}"
        covered_ids.add(r.asset.id)
        parent_evidences.append(
            Evidence(
                asset=r.asset,
                used_layer=AccessLayer.original.value,
                snippet=scrubbed,
                seq=None,  # 文件级证据：seq 置空，引用落到文件
                weknora_chunk_ref=ref,  # server-only 追踪用，绝不外泄
            )
        )

    # 未覆盖资产（无原文权限 / 无 chunk / 超 N 篇 / 擦洗失败）→ 片段 / 摘要兜底。
    rest = [r for r in recalled if r.asset.id not in covered_ids]
    fallback = await gather_evidence(rest, desens, trace_id=trace_id)
    order = {r.asset.id: idx for idx, r in enumerate(recalled)}
    combined = parent_evidences + fallback
    combined.sort(key=lambda e: order.get(e.asset.id, len(recalled)))
    return combined


_ANSWER_SYSTEM_PROMPT = (
    "你是企业知识助手。**只能**依据下方提供的知识片段回答用户问题，不得编造片段外的事实；"
    "不足以回答时直说依据不足。在句末用 [序号] 标注引用来源。"
    "当多个文件提供的信息需要对照时，请交叉综合后再回答，不要只引用单篇内容。"
    "输出简洁中文答案，不要复述提示。"
)


async def synthesize_answer(
    llm: LLMClient | NullLLMClient,
    query: str,
    evidences: list[Evidence],
    *,
    trace_id: str | None,
) -> str | None:
    """喂放行+脱敏证据给外部 LLM 自拼答案；LLM 不可用 / 无证据 → None。"""
    if not evidences:
        return None
    blocks = [
        f"[{i}] 《{e.asset.title}》（保密 {e.asset.confidentiality_level}）：\n{e.snippet}"
        for i, e in enumerate(evidences, start=1)
    ]
    try:
        answer = await llm.chat_completion(
            [
                {"role": "system", "content": _ANSWER_SYSTEM_PROMPT},
                {"role": "user", "content": f"问题：{query}\n\n知识片段：\n" + "\n".join(blocks)},
            ],
            temperature=0.2,
            json_object=False,
            trace_id=trace_id,
        )
    except LLMError:
        return None
    answer = (answer or "").strip()
    return answer or None


# ---------------------------------------------------------------------------
# 阶段2：单资产原文（三道过滤）
# ---------------------------------------------------------------------------
@dataclass
class OriginalResult:
    """阶段2原文结果。available=False 时 chunks 为空，调用方只给卡片+联系人。"""

    asset: KnowledgeAsset | None
    available: bool
    chunks: list[dict]  # [{seq, content(已脱敏)}]
    degraded_reason: str | None = None
    owner_name: str | None = None
    maintainer_name: str | None = None


async def fetch_stage2_original(
    session: AsyncSession,
    caller: CallerContext,
    weknora: WeKnoraClient | NullWeKnoraClient,
    desens: OutputDesensitizer,
    *,
    asset_id: uuid.UUID,
    query: str,
    channel: AccessChannel,
    trace_id: str | None,
) -> OriginalResult:
    """取某资产原文（三道过滤）。无原文权限 → available=False（只回卡片+联系人，不给 chunk）。"""
    asset = (
        await session.execute(
            select(KnowledgeAsset)
            .where(KnowledgeAsset.id == asset_id)
            .options(selectinload(KnowledgeAsset.summaries), selectinload(KnowledgeAsset.tags))
        )
    ).scalar_one_or_none()
    if asset is None:
        return OriginalResult(asset=None, available=False, chunks=[], degraded_reason="not_found")

    # 发现层先判：不可发现的（他人个人 / 无权 L5 / archived）一律按不存在处理，不泄露。
    # L1/L2 原文默认放行由运行时 policy 决定。
    policy = await load_access_policy(session)
    if not decide(caller, asset, AccessLayer.discovery, channel=channel, policy=policy).allowed:
        return OriginalResult(asset=None, available=False, chunks=[], degraded_reason="not_found")

    # 第②道：逐 chunk 复核的资产级前置——原文权限判断（无权 → 只给卡片+联系人）。
    # 叠加 active access_grant（外部 Agent / 问答 / 检索原文取件统一口径）。
    has_grant = await original_access.has_active_grant(session, caller.user_id, asset.id)
    o = decide(
        caller,
        asset,
        AccessLayer.original,
        channel=channel,
        has_original_grant=has_grant,
        policy=policy,
    )
    _projects, users = await load_card_aux(session, [asset])
    owner_name = users.get(asset.owner_user_id) if asset.owner_user_id else None
    maintainer_name = users.get(asset.maintainer_user_id) if asset.maintainer_user_id else None
    if (
        asset.scope == KnowledgeScope.project.value
        and asset.project_id not in caller.active_project_ids
    ):
        # 原文授权不等同项目成员身份；跨项目检索始终不返回成员信息。
        owner_name = None
        maintainer_name = None
    if not o.allowed:
        return OriginalResult(
            asset=asset,
            available=False,
            chunks=[],
            degraded_reason=o.denied_reason.value,
            owner_name=owner_name,
            maintainer_name=maintainer_name,
        )

    # 取该资产 active 版本的 weknora_doc_id / kb_id（第①道：限定到本资产、本 KB）。
    version = (
        await session.execute(
            select(KnowledgeAssetVersion)
            .where(KnowledgeAssetVersion.asset_id == asset.id)
            .where(KnowledgeAssetVersion.version_status == _ACTIVE_VERSION)
        )
    ).scalar_one_or_none()
    # residual：index_status 非 indexed（index_failed/not_indexed/skipped）即使残留
    # server-only weknora_doc_id，也按未索引处理——不读取底座旧 doc（降级 original_unindexed）。
    if (
        version is None
        or not version.weknora_doc_id
        or not version.weknora_kb_id
        or version.index_status != _INDEXED_STATUS
    ):
        return OriginalResult(
            asset=asset,
            available=False,
            chunks=[],
            degraded_reason="original_unindexed",
            owner_name=owner_name,
            maintainer_name=maintainer_name,
        )

    raw_chunks = await weknora.search(
        query=query,
        kb_ids=[version.weknora_kb_id],
        knowledge_ids=[version.weknora_doc_id],
        top_k=_RECALL_TOP_K,
        trace_id=trace_id,
    )
    # 第②道：逐 chunk 复核——只接受确实映射回本资产 doc 的 chunk（防 KB 内混入越权资产）。
    out_chunks: list[dict] = []
    scrub_failed = False
    for c in raw_chunks:
        if c.get("knowledge_id") != version.weknora_doc_id:
            continue
        content = (c.get("content") or "").strip()
        if not content:
            continue
        # 第③道：输出脱敏（L3/L4/L5 必脱敏；脱敏不可用 → 保守丢弃该片段）。
        scrubbed = await _scrub_chunk(desens, asset, content, trace_id=trace_id)
        if not scrubbed:
            scrub_failed = True
            continue
        out_chunks.append({"seq": c.get("seq"), "content": scrubbed})

    if not out_chunks:
        # 有权但脱敏全失败（LLM 不可用）→ 保守降级：不返回原文。
        reason = "desensitization_unavailable" if scrub_failed else "original_unindexed"
        return OriginalResult(
            asset=asset,
            available=False,
            chunks=[],
            degraded_reason=reason,
            owner_name=owner_name,
            maintainer_name=maintainer_name,
        )
    return OriginalResult(
        asset=asset,
        available=True,
        chunks=out_chunks,
        owner_name=owner_name,
        maintainer_name=maintainer_name,
    )
