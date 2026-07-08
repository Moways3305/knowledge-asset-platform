import { useState, useMemo, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { ShieldAlert } from "lucide-react";
import { fetchAuthMe, type AuthMeVM } from "../api/auth";
import {
  deleteKnowledgeAsset,
  fetchKnowledgeList,
  fetchKnowledgeOpsInsights,
  searchKnowledge,
} from "../api/knowledge";
import { ApiError } from "../api/http";
import type { KnowledgeOpsInsightsDTO } from "../types/insights";
import type { FrontVisibility, KnowledgeCardVM, KnowledgeScope } from "../types/knowledge";
import type { SearchResponseDTO } from "../types/search";
import { scopeLabels } from "../utils/knowledgeLabels";
import KnowledgeSearchBar from "./knowledge/KnowledgeSearchBar";
import KnowledgeCardList from "./knowledge/KnowledgeCardList";
import OpsInsightsPanel from "./knowledge/OpsInsightsPanel";
import CreateProjectModal from "./knowledge/CreateProjectModal";

const scopes: KnowledgeScope[] = ["company", "project", "personal"];

type SortKey = "updatedAt" | "confidence";

const sortLabels: Record<SortKey, string> = {
  updatedAt: "更新时间优先",
  confidence: "置信度优先",
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

  // 三个 scope 的列表数据，按 includeArchived 重新拉取。
  const [byScope, setByScope] = useState<Record<KnowledgeScope, KnowledgeCardVM[]> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // 语义搜索状态。
  const [searchResult, setSearchResult] = useState<SearchResponseDTO | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  const navigate = useNavigate();
  // 创建项目知识库：仅 boss / 咨询总监可见入口。
  const [authMe, setAuthMe] = useState<AuthMeVM | null>(null);
  const [projFormOpen, setProjFormOpen] = useState(false);
  // 浏览卡片删除：两步内联确认。
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleteBusyId, setDeleteBusyId] = useState<string | null>(null);
  // 右侧运营洞察。
  const [insights, setInsights] = useState<KnowledgeOpsInsightsDTO | null>(null);
  const [insightsErr, setInsightsErr] = useState(false);

  const searchMode = committedQuery.trim().length > 0;

  const loadList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [company, project, personal] = await Promise.all(
        scopes.map((s) => fetchKnowledgeList({ scope: s, includeArchived })),
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
    fetchAuthMe()
      .then(setAuthMe)
      .catch(() => setAuthMe(null));
  }, []);

  // 按当前 scope 拉取运营洞察。
  useEffect(() => {
    let cancelled = false;
    setInsightsErr(false);
    fetchKnowledgeOpsInsights({ scope: activeScope })
      .then((d) => {
        if (!cancelled) setInsights(d);
      })
      .catch(() => {
        if (!cancelled) {
          setInsights(null);
          setInsightsErr(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [activeScope]);

  const canCreateProject = useMemo(
    () => !!authMe && authMe.companyRoles.some((r) => r === "boss" || r === "consulting_director"),
    [authMe],
  );

  const openProjectForm = useCallback(() => setProjFormOpen(true), []);

  const handleDeleteCard = useCallback(
    async (assetId: string) => {
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
    },
    [loadList],
  );

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
        setSearchError(e instanceof ApiError ? e.message : "搜索暂时无法完成，请稍后重试");
        setSearchLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [committedQuery, activeScope, filterBizStage, includeArchived]);

  const allAssets = useMemo(
    () => (byScope ? [...byScope.company, ...byScope.project, ...byScope.personal] : []),
    [byScope],
  );

  const projectOptions = useMemo(
    () => Array.from(new Set(allAssets.map((a) => a.projectName).filter(Boolean))).sort(),
    [allAssets],
  );
  const bizStageOptions = useMemo(
    () => Array.from(new Set(allAssets.map((a) => a.lifecyclePhase).filter(Boolean))).sort(),
    [allAssets],
  );
  const assetTypeOptions = useMemo(
    () => Array.from(new Set(allAssets.map((a) => a.assetType))).sort(),
    [allAssets],
  );
  const visibilityOptions = useMemo(
    () => Array.from(new Set(allAssets.map((a) => a.visibility))).sort() as FrontVisibility[],
    [allAssets],
  );

  // 浏览模式筛选（项目 / 资料类型 / 可见性）。语义搜索模式下这些不由后端搜索驱动。
  const hasActiveFilters = !!(
    filterProject ||
    filterBizStage ||
    filterAssetType ||
    filterVisibility
  );

  const resetFilters = useCallback(() => {
    setFilterProject("");
    setFilterBizStage("");
    setFilterAssetType("");
    setFilterVisibility("");
    setSortKey("updatedAt");
  }, []);

  const runSearch = useCallback(() => setCommittedQuery(search.trim()), [search]);

  const clearSearch = useCallback(() => {
    setSearch("");
    setCommittedQuery("");
  }, []);

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
  }, [
    byScope,
    activeScope,
    filterProject,
    filterBizStage,
    filterAssetType,
    filterVisibility,
    sortKey,
  ]);

  const activeAssets = allAssets.filter((a) => a.assetStatus !== "archived");
  const totalAssets = activeAssets.length;
  const reusableCount = activeAssets.filter((a) => a.visibility === "public").length;
  const attentionCount = activeAssets.filter((a) => a.assetStatus === "needs_update").length;
  const archivedCount = allAssets.filter((a) => a.assetStatus === "archived").length;

  const cards = searchResult?.cards ?? [];

  return (
    <div className="kb">
      <div className="kb-masthead">
        <div className="kb-masthead-text">
          <div className="kb-eyebrow">Knowledge Base · 知识资产</div>
          <h2 className="kb-title">知识资产库</h2>
          <p className="kb-lead">浏览、语义检索与复用组织沉淀的知识资产</p>
        </div>
        <div className="kb-metrics">
          <div className="kb-metric">
            <div className="kb-metric-value">{totalAssets}</div>
            <div className="kb-metric-label">总资产</div>
          </div>
          <div className="kb-metric">
            <div className="kb-metric-value is-success">{reusableCount}</div>
            <div className="kb-metric-label">可复用</div>
          </div>
          <div className="kb-metric">
            <div className="kb-metric-value is-warning">{attentionCount}</div>
            <div className="kb-metric-label">需关注</div>
          </div>
          <div className="kb-metric">
            <div className="kb-metric-value is-muted">{archivedCount}</div>
            <div className="kb-metric-label">已归档</div>
          </div>
        </div>
      </div>

      {/* 纯系统管理身份（admin）非业务身份，后端不放行任何业务知识；短句说明，不展示业务列表。 */}
      {authMe && !authMe.isBusinessUser && (
        <div className="kb-identity-note">
          <ShieldAlert size={16} />
          <span>
            当前为系统管理身份，仅显示运营入口；业务知识请使用具备项目或公司角色的账号查看。
          </span>
        </div>
      )}

      <div className="kb-scope">
        {scopes.map((s) => (
          <button
            key={s}
            className={`kb-scope-btn ${activeScope === s ? "active" : ""}`}
            onClick={() => setActiveScope(s)}
          >
            {scopeLabels[s]}
            <span className="kb-scope-count">{byScope ? byScope[s].length : 0}</span>
          </button>
        ))}
      </div>

      <KnowledgeSearchBar
        search={search}
        setSearch={setSearch}
        runSearch={runSearch}
        clearSearch={clearSearch}
        searchMode={searchMode}
        filterProject={filterProject}
        setFilterProject={setFilterProject}
        filterBizStage={filterBizStage}
        setFilterBizStage={setFilterBizStage}
        filterAssetType={filterAssetType}
        setFilterAssetType={setFilterAssetType}
        filterVisibility={filterVisibility}
        setFilterVisibility={setFilterVisibility}
        projectOptions={projectOptions}
        bizStageOptions={bizStageOptions}
        assetTypeOptions={assetTypeOptions}
        visibilityOptions={visibilityOptions}
        hasActiveFilters={hasActiveFilters}
        resetFilters={resetFilters}
      />

      <div className="kb-body">
        <div className="kb-main">
          <div className="kb-toolbar">
            <span className="kb-result-count">
              <span className={`kb-mode-tag ${searchMode ? "kb-mode-search" : "kb-mode-browse"}`}>
                {searchMode ? "语义检索" : "浏览"}
              </span>
              {searchMode
                ? `检索到 ${cards.length} 条结果`
                : `共 ${filtered.length} 条${scopeLabels[activeScope]}资产`}
            </span>
            <div className="kb-toolbar-right">
              {activeScope === "project" && !searchMode && canCreateProject && (
                <button className="btn-small btn-small-primary" onClick={openProjectForm}>
                  新建项目知识库
                </button>
              )}
              <label className="kb-archive-toggle">
                <input
                  type="checkbox"
                  checked={includeArchived}
                  onChange={(e) => setIncludeArchived(e.target.checked)}
                />
                <span>包含归档</span>
              </label>
              <select
                className="kb-sort"
                value={sortKey}
                disabled={searchMode}
                title={searchMode ? "语义搜索按相关度排序" : undefined}
                onChange={(e) => setSortKey(e.target.value as SortKey)}
              >
                {(Object.keys(sortLabels) as SortKey[]).map((k) => (
                  <option key={k} value={k}>
                    {sortLabels[k]}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <KnowledgeCardList
            searchMode={searchMode}
            searchLoading={searchLoading}
            searchError={searchError}
            searchResult={searchResult}
            runSearch={runSearch}
            loading={loading}
            error={error}
            filtered={filtered}
            activeScope={activeScope}
            canCreateProject={canCreateProject}
            openProjectForm={openProjectForm}
            resetFilters={resetFilters}
            hasActiveFilters={hasActiveFilters}
            confirmDeleteId={confirmDeleteId}
            deleteBusyId={deleteBusyId}
            onAskDelete={setConfirmDeleteId}
            onCancelDelete={() => setConfirmDeleteId(null)}
            onConfirmDelete={(id) => void handleDeleteCard(id)}
          />
        </div>

        <OpsInsightsPanel insights={insights} insightsErr={insightsErr} />
      </div>

      {/* 新建项目知识库：仅 boss / 咨询总监；创建真实 projects + active project_manager。 */}
      <CreateProjectModal
        open={projFormOpen}
        onClose={() => setProjFormOpen(false)}
        onCreated={(created) => {
          setProjFormOpen(false);
          navigate(`/project/${created.id}/settings`);
        }}
      />
    </div>
  );
}
