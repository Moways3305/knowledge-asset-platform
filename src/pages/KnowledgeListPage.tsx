import { useState, useMemo, useEffect, useCallback } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  Search, ShieldAlert, AlertTriangle, FileSearch, CheckCircle2, KeyRound,
  Radar, Trash2, Sparkles,
} from "lucide-react";
import {
  ApiError,
  createProject,
  deleteKnowledgeAsset,
  fetchAuthMe,
  fetchKnowledgeList,
  fetchKnowledgeOpsInsights,
  fetchWecomScanOwnerOptions,
  searchKnowledge,
  type AuthMeVM,
} from "../api/client";
import type { KnowledgeOpsInsightsDTO } from "../types/insights";
import type {
  AssetStatus,
  FrontVisibility,
  KnowledgeCardVM,
  KnowledgeScope,
} from "../types/knowledge";
import type { SearchResponseDTO } from "../types/search";
import type { WecomOwnerOptionDTO } from "../types/wecom";
import { formatBeijingTime } from "../utils/time";

const scopeLabels: Record<KnowledgeScope, string> = {
  personal: "个人知识",
  project: "项目知识",
  company: "公司知识",
};

const scopes: KnowledgeScope[] = ["company", "project", "personal"];

const assetTypeLabel: Record<string, string> = {
  methodology: "方法论",
  deliverable: "交付物",
  case: "案例",
  template: "模板",
  insight: "洞察",
};

const visibilityLabel: Record<FrontVisibility, string> = {
  public: "公开",
  "project-only": "项目内",
  confidential: "机密",
};

const assetStatusLabel: Record<AssetStatus, string> = {
  active: "活跃",
  needs_update: "待更新",
  deprecated: "已废弃",
  archived: "已归档",
};

type SortKey = "updatedAt" | "confidence";

const sortLabels: Record<SortKey, string> = {
  updatedAt: "更新时间优先",
  confidence: "置信度优先",
};

// 检索意图（后端 R3 分类结果）中文标签。
const intentLabel: Record<string, string> = {
  search: "查找",
  qa: "问答",
  generate: "生成",
  recommend: "推荐",
  check: "检查",
  summarize: "总结",
};

// 三层访问模型标签（发现 / 摘要 / 原文）。
const accessLayerLabel: Record<string, string> = {
  discovery: "发现层",
  summary: "摘要层",
  original: "原文层",
};

const zoneLabel = (zone: string) => (zone === "asset" ? "资产区" : zone === "material" ? "资料区" : zone);

// 平台级底座索引状态（小角标）。indexed 为常态，不展示角标。
const indexStatusLabel: Record<string, string> = {
  indexing: "索引中",
  index_failed: "索引失败",
  skipped: "未索引底座",
  not_indexed: "待索引",
};

// 档案脊颜色：搜索卡按真实保密级（L1–L5）；浏览卡按可见性近似（不虚构保密级）。
const spineByLevel = (level: string) => `conf-${level}`;
const spineByVisibility = (v: FrontVisibility) =>
  v === "public" ? "conf-L1" : v === "confidential" ? "conf-L4" : "conf-L2";

const confidenceText = (c: number | null) => {
  if (c == null) return "—";
  const pct = Math.round(c * 100);
  const level = c >= 0.9 ? "高" : c >= 0.8 ? "中" : "低";
  return `${level}（${pct}%）`;
};

export default function KnowledgeListPage() {
  const [activeScope, setActiveScope] = useState<KnowledgeScope>("company");
  const [search, setSearch] = useState("");
  // committedQuery 非空 = 进入语义搜索模式；为空 = 浏览模式。
  const [committedQuery, setCommittedQuery] = useState("");
  const [filterProject, setFilterProject] = useState("");
  const [filterBizStage, setFilterBizStage] = useState("");
  const [filterAssetType, setFilterAssetType] = useState("");
  const [filterVisibility, setFilterVisibility] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("updatedAt");
  const [includeArchived, setIncludeArchived] = useState(false);

  // 三个 scope 的列表数据，从后端真实 API 获取（按 includeArchived 重新拉取）。
  const [byScope, setByScope] = useState<Record<KnowledgeScope, KnowledgeCardVM[]> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 语义搜索状态（POST /knowledge/search 真实结果）。
  const [searchResult, setSearchResult] = useState<SearchResponseDTO | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const navigate = useNavigate();
  // 创建项目知识库：仅 boss / 咨询总监可见入口。
  const [authMe, setAuthMe] = useState<AuthMeVM | null>(null);
  const [ownerOptions, setOwnerOptions] = useState<WecomOwnerOptionDTO[]>([]);
  const [projFormOpen, setProjFormOpen] = useState(false);
  const [pfName, setPfName] = useState("");
  const [pfClient, setPfClient] = useState("");
  const [pfPm, setPfPm] = useState("");
  const [pfCoach, setPfCoach] = useState("");
  const [pfBusy, setPfBusy] = useState(false);
  const [pfError, setPfError] = useState<string | null>(null);
  // 浏览卡片删除：两步内联确认。
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleteBusyId, setDeleteBusyId] = useState<string | null>(null);
  // 右侧运营洞察（真实后端安全聚合，替换本地规则提示）。
  const [insights, setInsights] = useState<KnowledgeOpsInsightsDTO | null>(null);
  const [insightsErr, setInsightsErr] = useState(false);

  const searchMode = committedQuery.trim().length > 0;

  const loadList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [company, project, personal] = await Promise.all(
        scopes.map((s) => fetchKnowledgeList({ scope: s, includeArchived }))
      );
      setByScope({ company, project, personal });
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [includeArchived]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    fetchAuthMe().then(setAuthMe).catch(() => setAuthMe(null));
  }, []);

  // 按当前 scope 拉取真实运营洞察。失败 → 安全错误态，不回退假数据。
  useEffect(() => {
    let cancelled = false;
    setInsightsErr(false);
    fetchKnowledgeOpsInsights({ scope: activeScope })
      .then((d) => { if (!cancelled) setInsights(d); })
      .catch(() => { if (!cancelled) { setInsights(null); setInsightsErr(true); } });
    return () => { cancelled = true; };
  }, [activeScope]);

  const canCreateProject = useMemo(
    () => !!authMe && authMe.companyRoles.some((r) => r === "boss" || r === "consulting_director"),
    [authMe]
  );

  // 打开创建表单时按需加载业务用户候选（项目经理 / 辅导老师），真实后端来源。
  const openProjectForm = useCallback(() => {
    setPfName(""); setPfClient(""); setPfPm(""); setPfCoach("");
    setPfError(null); setProjFormOpen(true);
    fetchWecomScanOwnerOptions().then((d) => setOwnerOptions(d.items)).catch(() => setOwnerOptions([]));
  }, []);

  const handleCreateProject = useCallback(async () => {
    setPfError(null);
    if (!pfName.trim()) { setPfError("请填写项目名称"); return; }
    if (!pfPm) { setPfError("请选择项目经理"); return; }
    setPfBusy(true);
    try {
      const created = await createProject({
        name: pfName.trim(),
        client_name: pfClient.trim() || null,
        project_manager_user_id: pfPm,
        coach_user_id: pfCoach || null,
        lifecycle_route_key: "route_A",
      });
      setProjFormOpen(false);
      navigate(`/project/${created.id}/settings`);
    } catch (e) {
      setPfError(e instanceof ApiError ? `${e.message}（${e.deniedReason ?? e.status}）` : "创建项目失败");
    } finally {
      setPfBusy(false);
    }
  }, [pfName, pfClient, pfPm, pfCoach, navigate]);

  const handleDeleteCard = useCallback(async (assetId: string) => {
    setDeleteBusyId(assetId);
    try {
      await deleteKnowledgeAsset(assetId);
      setConfirmDeleteId(null);
      await loadList();
    } catch {
      // 失败保持卡片，错误在确认区提示（保守：仅清 busy）。
    } finally {
      setDeleteBusyId(null);
    }
  }, [loadList]);

  // 语义搜索：committedQuery 非空时调用后端，scope/业务阶段/归档随之重检索。
  // 后端驱动的过滤项：scope（tab）、phase（业务阶段）、include_archived。
  useEffect(() => {
    const q = committedQuery.trim();
    if (!q) {
      setSearchResult(null);
      setSearchError(null);
      setSearchLoading(false);
      return;
    }
    let cancelled = false;
    setSearchLoading(true);
    setSearchError(null);
    searchKnowledge({
      query: q,
      scope: activeScope,
      filters: {
        phase: filterBizStage || null,
        include_archived: includeArchived,
      },
    })
      .then((res) => {
        if (cancelled) return;
        setSearchResult(res);
        setSearchLoading(false);
      })
      .catch((e) => {
        if (cancelled) return;
        setSearchError(e instanceof ApiError ? e.message : "搜索失败，请稍后重试（请确认后端服务已启动）");
        setSearchLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [committedQuery, activeScope, filterBizStage, includeArchived]);

  const allAssets = useMemo(
    () => (byScope ? [...byScope.company, ...byScope.project, ...byScope.personal] : []),
    [byScope]
  );

  const projectOptions = useMemo(
    () => Array.from(new Set(allAssets.map((a) => a.projectName).filter(Boolean))).sort(),
    [allAssets]
  );
  const bizStageOptions = useMemo(
    () => Array.from(new Set(allAssets.map((a) => a.lifecyclePhase).filter(Boolean))).sort(),
    [allAssets]
  );
  const assetTypeOptions = useMemo(
    () => Array.from(new Set(allAssets.map((a) => a.assetType))).sort(),
    [allAssets]
  );
  const visibilityOptions = useMemo(
    () => Array.from(new Set(allAssets.map((a) => a.visibility))).sort(),
    [allAssets]
  );

  // 浏览模式筛选（项目 / 资料类型 / 可见性）。语义搜索模式下这些不由后端搜索驱动。
  const hasActiveFilters = filterProject || filterBizStage || filterAssetType || filterVisibility;

  function resetFilters() {
    setFilterProject("");
    setFilterBizStage("");
    setFilterAssetType("");
    setFilterVisibility("");
    setSortKey("updatedAt");
  }

  function runSearch() {
    setCommittedQuery(search.trim());
  }

  function clearSearch() {
    setSearch("");
    setCommittedQuery("");
  }

  // 浏览模式列表：仅用浏览筛选（项目 / 阶段 / 类型 / 可见性）+ 排序；查询文本只驱动语义搜索。
  const filtered = useMemo(() => {
    if (!byScope) return [];
    let result = [...byScope[activeScope]];
    if (filterProject) result = result.filter((a) => a.projectName === filterProject);
    if (filterBizStage) result = result.filter((a) => a.lifecyclePhase === filterBizStage);
    if (filterAssetType) result = result.filter((a) => a.assetType === filterAssetType);
    if (filterVisibility) result = result.filter((a) => a.visibility === filterVisibility);

    result.sort((a, b) => {
      if (sortKey === "confidence") return (b.confidence ?? 0) - (a.confidence ?? 0);
      return b.updatedAt.localeCompare(a.updatedAt);
    });
    return result;
  }, [byScope, activeScope, filterProject, filterBizStage, filterAssetType, filterVisibility, sortKey]);

  const activeAssets = allAssets.filter((a) => a.assetStatus !== "archived");
  const totalAssets = activeAssets.length;
  const reusableCount = activeAssets.filter((a) => a.visibility === "public").length;
  const attentionCount = activeAssets.filter((a) => a.assetStatus === "needs_update").length;
  const archivedCount = allAssets.filter((a) => a.assetStatus === "archived").length;

  const cards = searchResult?.cards ?? [];
  const citations = searchResult?.citations ?? [];

  return (
    <div className="kb">
      <div className="kb-masthead">
        <div className="kb-masthead-text">
          <div className="kb-eyebrow">Knowledge Base · 知识资产</div>
          <h2 className="kb-title">知识资产库</h2>
          <p className="kb-lead">浏览、语义检索与复用组织沉淀的知识资产</p>
        </div>
        <div className="kb-metrics">
          <div className="kb-metric"><div className="kb-metric-value">{totalAssets}</div><div className="kb-metric-label">总资产</div></div>
          <div className="kb-metric"><div className="kb-metric-value is-success">{reusableCount}</div><div className="kb-metric-label">可复用</div></div>
          <div className="kb-metric"><div className="kb-metric-value is-warning">{attentionCount}</div><div className="kb-metric-label">需关注</div></div>
          <div className="kb-metric"><div className="kb-metric-value is-muted">{archivedCount}</div><div className="kb-metric-label">已归档</div></div>
        </div>
      </div>

      {/* 纯系统管理身份（admin）非业务身份，后端不放行任何业务知识；短句说明，不展示业务列表。 */}
      {authMe && !authMe.isBusinessUser && (
        <div className="kb-identity-note">
          <ShieldAlert size={16} />
          <span>当前为系统管理身份（admin），不具备业务知识访问权；业务知识仅对业务用户（顾问 / 项目经理 / Boss / 咨询总监）开放。运营元数据请使用管理后台（入库管理 / 微盘扫描 / 审计）。</span>
        </div>
      )}

      <div className="kb-scope">
        {scopes.map((s) => (
          <button key={s} className={`kb-scope-btn ${activeScope === s ? "active" : ""}`} onClick={() => setActiveScope(s)}>
            {scopeLabels[s]}
            <span className="kb-scope-count">{byScope ? byScope[s].length : 0}</span>
          </button>
        ))}
      </div>

      <div className="kb-search">
        <div className="kb-search-field">
          <Search size={17} className="kb-search-icon" />
          <input
            type="text"
            placeholder="语义检索：输入问题或关键词，回车检索（WeKnora 召回 + 权限裁剪）"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") runSearch(); }}
          />
        </div>
        <button className="btn-primary" onClick={runSearch} disabled={!search.trim()}>搜索</button>
        {searchMode && <button className="btn-secondary" onClick={clearSearch}>返回浏览</button>}
      </div>

      <div className="kb-filters">
        <div className="kb-filter">
          <label>项目{searchMode ? "（仅浏览）" : ""}</label>
          <select value={filterProject} disabled={searchMode} onChange={(e) => setFilterProject(e.target.value)}>
            <option value="">全部</option>
            {projectOptions.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
        <div className="kb-filter">
          <label>业务阶段{searchMode ? "（检索过滤）" : ""}</label>
          <select value={filterBizStage} onChange={(e) => setFilterBizStage(e.target.value)}>
            <option value="">全部</option>
            {bizStageOptions.map((o) => <option key={o} value={o}>{o}</option>)}
          </select>
        </div>
        <div className="kb-filter">
          <label>资料类型{searchMode ? "（仅浏览）" : ""}</label>
          <select value={filterAssetType} disabled={searchMode} onChange={(e) => setFilterAssetType(e.target.value)}>
            <option value="">全部</option>
            {assetTypeOptions.map((o) => <option key={o} value={o}>{assetTypeLabel[o] ?? o}</option>)}
          </select>
        </div>
        <div className="kb-filter">
          <label>可见性{searchMode ? "（仅浏览）" : ""}</label>
          <select value={filterVisibility} disabled={searchMode} onChange={(e) => setFilterVisibility(e.target.value)}>
            <option value="">全部</option>
            {visibilityOptions.map((o) => <option key={o} value={o}>{visibilityLabel[o]}</option>)}
          </select>
        </div>
        {hasActiveFilters && !searchMode && (
          <button className="btn-reset-filter" onClick={resetFilters}>清除筛选</button>
        )}
      </div>

      <div className="kb-body">
        <div className="kb-main">
          <div className="kb-toolbar">
            <span className="kb-result-count">
              <span className={`kb-mode-tag ${searchMode ? "kb-mode-search" : "kb-mode-browse"}`}>
                {searchMode ? "语义检索" : "浏览"}
              </span>
              {searchMode ? `检索到 ${cards.length} 条结果` : `共 ${filtered.length} 条${scopeLabels[activeScope]}资产`}
            </span>
            <div className="kb-toolbar-right">
              {activeScope === "project" && !searchMode && canCreateProject && (
                <button className="btn-small btn-small-primary" onClick={openProjectForm}>新建项目知识库</button>
              )}
              <label className="kb-archive-toggle">
                <input type="checkbox" checked={includeArchived} onChange={(e) => setIncludeArchived(e.target.checked)} />
                <span>包含归档</span>
              </label>
              <select className="kb-sort" value={sortKey} disabled={searchMode}
                title={searchMode ? "语义搜索按相关度排序" : undefined}
                onChange={(e) => setSortKey(e.target.value as SortKey)}>
                {(Object.keys(sortLabels) as SortKey[]).map((k) => (<option key={k} value={k}>{sortLabels[k]}</option>))}
              </select>
            </div>
          </div>

          {searchMode ? (
            /* ════════ 语义搜索结果（真实 /knowledge/search）════════ */
            searchLoading ? (
              <div className="kb-state"><div className="kb-state-icon"><Search size={20} /></div><div className="kb-state-title">检索中…</div></div>
            ) : searchError ? (
              <div className="kb-state">
                <div className="kb-state-icon is-error"><AlertTriangle size={20} /></div>
                <div className="kb-state-title">检索失败</div>
                <p className="kb-state-desc">{searchError}</p>
                <button className="btn-secondary" onClick={runSearch}>重试</button>
              </div>
            ) : (
              <>
                {searchResult?.answer && (
                  <div className="kb-answer">
                    <div className="kb-answer-head">
                      <Sparkles size={13} />
                      <span className="kb-intent">{intentLabel[searchResult.intent] ?? searchResult.intent}</span>
                      <span>AI 答案 / 检索摘要</span>
                    </div>
                    <p className="kb-answer-text">{searchResult.answer}</p>
                    {citations.length > 0 && (
                      <div className="kb-citations">
                        <div className="kb-citations-title">引用来源</div>
                        <ul className="kb-citation-list">
                          {citations.map((c) => (
                            <li key={c.citation_order}>
                              <Link to={`/knowledge/${c.asset_id}`} className="kb-citation-title">
                                [{c.citation_order}] {c.asset_title}
                              </Link>
                              <span className="kb-citation-meta">
                                {accessLayerLabel[c.used_access_layer] ?? c.used_access_layer} · {zoneLabel(c.cited_zone)}
                              </span>
                              {c.snippet && <p className="kb-citation-snippet">{c.snippet}</p>}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </div>
                )}

                {cards.length > 0 ? (
                  <div className="kb-list">
                    {cards.map((card) => (
                      <article key={card.asset_id} className="dossier">
                        <div className={`dossier-spine ${spineByLevel(card.confidentiality_level)}`} />
                        <div className="dossier-body">
                          <div className="dossier-head">
                            <Link to={`/knowledge/${card.asset_id}`} className="dossier-title">{card.title}</Link>
                            <div className="dossier-badges">
                              <span className="dchip dchip-type">{assetTypeLabel[card.asset_type] ?? card.asset_type}</span>
                              <span className="dchip dchip-conf">{card.confidentiality_level}</span>
                              <span className="dchip dchip-zone">{zoneLabel(card.zone)}</span>
                            </div>
                          </div>
                          <p className="dossier-summary">{card.one_liner || card.detailed || "（无摘要权限）"}</p>
                          <div className="dossier-tags">
                            {card.tags.map((t) => <span key={t} className="tag">{t}</span>)}
                          </div>
                          <div className="dossier-meta">
                            {card.project_name && <span>{card.project_name}</span>}
                            {card.phase && <span>{card.phase}</span>}
                            <span className="u-num">相关度 {card.relevance_score.toFixed(2)}</span>
                            {card.updated_at && <span>{formatBeijingTime(card.updated_at)}</span>}
                          </div>
                          <div className="dossier-orig">
                            {card.can_view_original ? (
                              <span className="ok"><CheckCircle2 size={13} /> 可访问原文（经授权 / 项目权限）</span>
                            ) : (
                              <Link to={`/knowledge/${card.asset_id}`} className="need"><KeyRound size={13} /> 摘要层结果 · 原文需申请</Link>
                            )}
                          </div>
                        </div>
                      </article>
                    ))}
                  </div>
                ) : (
                  <div className="kb-state">
                    <div className="kb-state-icon"><FileSearch size={20} /></div>
                    <div className="kb-state-title">未检索到相关知识资产</div>
                    <p className="kb-state-desc">换个问法或关键词，切换知识库范围，或调整业务阶段过滤后重试。无结果也可能是你对相关知识没有发现权限。</p>
                  </div>
                )}

                {searchResult?.trace_id && (
                  <div className="kb-trace">检索追踪 ID：{searchResult.trace_id}</div>
                )}
              </>
            )
          ) : (
            /* ════════ 浏览模式列表 ════════ */
            loading ? (
              <div className="kb-state"><div className="kb-state-icon"><Radar size={20} /></div><div className="kb-state-title">加载中…</div></div>
            ) : error ? (
              <div className="kb-state">
                <div className="kb-state-icon is-error"><AlertTriangle size={20} /></div>
                <div className="kb-state-title">加载失败</div>
                <p className="kb-state-desc">{error}（请确认后端服务已启动）</p>
              </div>
            ) : filtered.length > 0 ? (
              <div className="kb-list">
                {filtered.map((asset) => {
                  const idxCls = asset.indexStatus === "indexing" ? "idx-indexing"
                    : asset.indexStatus === "index_failed" ? "idx-failed"
                    : asset.indexStatus === "skipped" ? "idx-skipped" : "idx-pending";
                  return (
                  <article key={asset.id} className={`dossier ${asset.assetStatus === "archived" ? "is-archived" : ""}`}>
                    <div className={`dossier-spine ${spineByVisibility(asset.visibility)}`} />
                    <div className="dossier-body">
                      <div className="dossier-head">
                        <Link to={`/knowledge/${asset.id}`} className="dossier-title">{asset.title}</Link>
                        <div className="dossier-badges">
                          <span className="dchip dchip-type">{assetTypeLabel[asset.assetType] ?? asset.assetType}</span>
                          <span className={`dchip dchip-vis-${asset.visibility}`}>{visibilityLabel[asset.visibility]}</span>
                          {asset.assetStatus !== "active" && (
                            <span className="dchip dchip-status">{assetStatusLabel[asset.assetStatus]}</span>
                          )}
                        </div>
                      </div>
                      <p className="dossier-summary">{asset.summary || (asset.access.summary ? "" : "（无摘要权限）")}</p>
                      <div className="dossier-tags">
                        {asset.tags.map((t) => <span key={t} className="tag">{t}</span>)}
                      </div>
                      <div className="dossier-meta">
                        {asset.projectName && <span>{asset.projectName}</span>}
                        {asset.lifecyclePhase && <span>{asset.lifecyclePhase}</span>}
                        {asset.confidence != null && <span className="u-num">置信度 {confidenceText(asset.confidence)}</span>}
                        {asset.updatedAt && <span>{formatBeijingTime(asset.updatedAt)}</span>}
                        {asset.indexStatus && asset.indexStatus !== "indexed" && (
                          <span className={`dossier-index ${idxCls}`} title={asset.indexErrorMessage ?? "知识底座索引状态"}>
                            {indexStatusLabel[asset.indexStatus] ?? asset.indexStatus}
                          </span>
                        )}
                      </div>
                      {asset.access.canDelete && asset.assetStatus !== "archived" && (
                        <div className="dossier-actions">
                          {confirmDeleteId === asset.id ? (
                            <>
                              <span className="dossier-warn">删除后退出检索 / 问答 / 预览，保留审计。确认？</span>
                              <button className="btn-small btn-small-danger" disabled={deleteBusyId === asset.id} onClick={() => void handleDeleteCard(asset.id)}>
                                {deleteBusyId === asset.id ? "删除中…" : "确认删除"}
                              </button>
                              <button className="btn-small" onClick={() => setConfirmDeleteId(null)}>取消</button>
                            </>
                          ) : (
                            <button className="btn-small btn-small-danger" onClick={() => setConfirmDeleteId(asset.id)}><Trash2 size={13} /> 删除 / 撤下</button>
                          )}
                        </div>
                      )}
                    </div>
                  </article>
                  );
                })}
              </div>
            ) : (
              <div className="kb-state">
                <div className="kb-state-icon"><FileSearch size={20} /></div>
                <div className="kb-state-title">
                  {activeScope === "project" ? "该范围暂无项目知识资产" : "未找到匹配的知识资产"}
                </div>
                <p className="kb-state-desc">当前筛选条件下没有结果。尝试切换知识库范围或清除筛选条件，或在上方输入问题进行语义检索。</p>
                {activeScope === "project" && canCreateProject && (
                  <button className="btn-secondary" onClick={openProjectForm}>新建项目知识库</button>
                )}
                {hasActiveFilters && (
                  <button className="btn-secondary" onClick={resetFilters}>清除所有筛选</button>
                )}
              </div>
            )
          )}
        </div>

        <aside className="intel">
          <h4 className="intel-title"><Radar size={13} /> 运营洞察</h4>
          {insightsErr ? (
            <p className="intel-note">运营洞察加载失败（请确认后端已启动）。知识可见性与权限说明见 <Link to="/help#knowledge" className="page-help-link">使用说明 →</Link></p>
          ) : !insights ? (
            <p className="intel-note">加载运营洞察中…</p>
          ) : (
            <>
              {/* 真实后端安全聚合。颜色按 severity 派生，仅 UI 渲染，非业务事实来源。 */}
              {insights.cards.length === 0 && insights.recommendations.length === 0 ? (
                <p className="intel-note">暂无需要处理的运营项。</p>
              ) : (
                <>
                  {insights.cards.length > 0 && (
                    <div className="intel-cards">
                      {insights.cards.map((c) => (
                        <div key={c.key} className={`intel-card sev-${c.severity}`}>
                          <span className="intel-count">{c.count}</span>
                          <span className="intel-label">{c.label}</span>
                          {c.action_hint && <span className="intel-hint">{c.action_hint}</span>}
                        </div>
                      ))}
                    </div>
                  )}
                  {insights.recommendations.length > 0 && (
                    <ul className="intel-recos">
                      {insights.recommendations.map((r) => (
                        <li key={r.key} className={`intel-reco sev-${r.severity}`}>
                          {r.target ? <Link to={r.target}>{r.message}</Link> : <span>{r.message}</span>}
                        </li>
                      ))}
                    </ul>
                  )}
                </>
              )}
              {insights.recent_items.length > 0 && (
                <div className="intel-block">
                  <div className="intel-block-title">最近索引失败</div>
                  <ul>
                    {insights.recent_items.map((it) => (
                      <li key={it.asset_id} className="intel-item">
                        {insights.title_visible && it.title ? (
                          <Link to={`/knowledge/${it.asset_id}`}>{it.title}</Link>
                        ) : (
                          <span className="intel-hidden">（业务标题已隐藏）</span>
                        )}
                        {it.message && <span className="intel-item-msg">{it.message}</span>}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {insights.indexing.recent_jobs.length > 0 && (
                <div className="intel-block">
                  <div className="intel-block-title">最近运维作业</div>
                  <ul>
                    {insights.indexing.recent_jobs.map((j) => (
                      <li key={j.job_id} className="intel-item">
                        <span>{j.operation_type === "reparse" ? "重新解析" : "批量重试"} · {j.status}</span>
                        <span className="intel-item-msg">共 {j.total_count} / 成 {j.success_count} / 败 {j.failed_count}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="intel-foot">
                统计来自真实后端（{insights.window_days} 天窗口）{!insights.title_visible && "·系统运维视图（业务标题隐藏）"}。说明见 <Link to="/help#knowledge" className="page-help-link">使用说明 →</Link>
              </p>
            </>
          )}
        </aside>
      </div>

      {/* 新建项目知识库：仅 boss / 咨询总监；创建真实 projects + active project_manager。 */}
      {projFormOpen && (
        <div className="kl-modal-overlay" onClick={() => !pfBusy && setProjFormOpen(false)}>
          <div className="kl-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="kl-modal-title">新建项目知识库</h3>
            <p className="kl-modal-desc">创建真实项目知识空间，并指定项目经理（自动建立 active 成员关系）。项目知识库随项目存在，资料 / 资产在同一库内用 zone 区分。</p>
            <label className="kl-modal-field">
              <span>项目名称</span>
              <input value={pfName} onChange={(e) => setPfName(e.target.value)} maxLength={200} placeholder="如：某客户数字化转型项目" />
            </label>
            <label className="kl-modal-field">
              <span>客户名称（可选）</span>
              <input value={pfClient} onChange={(e) => setPfClient(e.target.value)} maxLength={200} />
            </label>
            <label className="kl-modal-field">
              <span>项目经理</span>
              <select value={pfPm} onChange={(e) => setPfPm(e.target.value)}>
                <option value="">请选择项目经理…</option>
                {ownerOptions.map((o) => (
                  <option key={o.user_id} value={o.user_id}>{o.name}{o.role_label ? `（${o.role_label}）` : ""}</option>
                ))}
              </select>
            </label>
            <label className="kl-modal-field">
              <span>辅导老师（可选）</span>
              <select value={pfCoach} onChange={(e) => setPfCoach(e.target.value)}>
                <option value="">不指定</option>
                {ownerOptions.filter((o) => o.user_id !== pfPm).map((o) => (
                  <option key={o.user_id} value={o.user_id}>{o.name}{o.role_label ? `（${o.role_label}）` : ""}</option>
                ))}
              </select>
            </label>
            <p className="kl-modal-hint">生命周期路线默认完整路线（route_A）。候选人来自真实后端 active 业务用户。</p>
            {pfError && <div className="kl-modal-error">{pfError}</div>}
            <div className="kl-modal-actions">
              <button className="btn-small btn-small-primary" onClick={() => void handleCreateProject()} disabled={pfBusy}>
                {pfBusy ? "创建中…" : "创建项目"}
              </button>
              <button className="btn-small" onClick={() => setProjFormOpen(false)} disabled={pfBusy}>取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

