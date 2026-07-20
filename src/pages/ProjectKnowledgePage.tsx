import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Bot, ChevronLeft, ChevronRight, FileText, MoreHorizontal, Search } from "lucide-react";
import { useNavigate, useParams } from "react-router-dom";
import { fetchKnowledgePage } from "../api/knowledge";
import { fetchProjectQaModelOptions, projectQa } from "../api/project";
import { requestCompanyUpgrade } from "../api/review";
import { useAuth } from "../auth/AuthContext";
import DataTable, { type Column } from "../components/DataTable";
import LoadingError from "../components/LoadingError";
import {
  EmptyState,
  FilterBar,
  PageHeader,
  PageSection,
  ProductPage,
} from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import type { ProjectQaModelOptionDTO, ProjectQaResponseDTO } from "../types/agent";
import type {
  AssetStatus,
  AssetType,
  ConfidentialityLevel,
  KnowledgeCardVM,
  KnowledgePageVM,
  KnowledgeQueryParams,
  KnowledgeSortField,
  KnowledgeZone,
  SortDirection,
} from "../types/knowledge";
import { assetStatusLabel, assetTypeLabel } from "../utils/knowledgeLabels";
import "./ProjectKnowledgePage.css";

const PAGE_SIZE = 20;
const SAFE_FALLBACK = "信息待确认";
const ASSET_TYPES: AssetType[] = ["methodology", "deliverable", "case", "template", "insight"];
const ASSET_STATUSES: AssetStatus[] = ["active", "needs_update", "deprecated", "archived"];
const CONFIDENTIALITY_LEVELS: ConfidentialityLevel[] = ["L1", "L2", "L3", "L4", "L5"];

const confidentialityLabels: Record<ConfidentialityLevel, string> = {
  L1: "L1 · 公开",
  L2: "L2 · 内部",
  L3: "L3 · 受限",
  L4: "L4 · 机密",
  L5: "L5 · 高度机密",
};

const statusTones: Record<AssetStatus, "success" | "warning" | "neutral"> = {
  active: "success",
  needs_update: "warning",
  deprecated: "neutral",
  archived: "neutral",
};

const emptyPage = (): KnowledgePageVM => ({
  items: [],
  total: 0,
  page: 1,
  pageSize: PAGE_SIZE,
  hasNext: false,
});

function pageNumbers(current: number, total: number): number[] {
  return [...new Set([1, current - 1, current, current + 1, total])].filter(
    (value) => value >= 1 && value <= total,
  );
}

function safeZone(value: string): string {
  if (value === "material") return "资料区";
  if (value === "asset") return "资产区";
  return SAFE_FALLBACK;
}

function safeType(value: string): string {
  return assetTypeLabel[value] ?? SAFE_FALLBACK;
}

function safeStatus(value: string): string {
  return assetStatusLabel[value as AssetStatus] ?? SAFE_FALLBACK;
}

function safeConfidentiality(value: string): string {
  return confidentialityLabels[value as ConfidentialityLevel] ?? SAFE_FALLBACK;
}

function ProjectKnowledgeWorkspace({
  project,
  projects,
  onSwitch,
}: {
  project: { projectId: string; projectName: string; projectRole: string };
  projects: Array<{ projectId: string; projectName: string; projectRole: string }>;
  onSwitch: (projectId: string) => void;
}) {
  const navigate = useNavigate();
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [zone, setZone] = useState<KnowledgeZone | "">("");
  const [assetType, setAssetType] = useState<AssetType | "">("");
  const [assetStatus, setAssetStatus] = useState<AssetStatus | "">("");
  const [confidentialityLevel, setConfidentialityLevel] = useState<ConfidentialityLevel | "">("");
  const [updatedFrom, setUpdatedFrom] = useState("");
  const [updatedTo, setUpdatedTo] = useState("");
  const [sortBy, setSortBy] = useState<KnowledgeSortField>("updated_at");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<KnowledgePageVM>(emptyPage);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [listRetryKey, setListRetryKey] = useState(0);
  const listRequestRef = useRef(0);

  const [qaOpen, setQaOpen] = useState(false);
  const [models, setModels] = useState<ProjectQaModelOptionDTO[]>([]);
  const [selectedModelIndex, setSelectedModelIndex] = useState("");
  const [modelsState, setModelsState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [modelsRetryKey, setModelsRetryKey] = useState(0);
  const modelRequestRef = useRef(0);
  const [qaInput, setQaInput] = useState("");
  const [qaQuestion, setQaQuestion] = useState("");
  const [qaResult, setQaResult] = useState<ProjectQaResponseDTO | null>(null);
  const [qaState, setQaState] = useState<"idle" | "loading" | "error">("idle");
  const qaRequestRef = useRef(0);

  const [upgradeBusyId, setUpgradeBusyId] = useState<string | null>(null);
  const [upgradeNotice, setUpgradeNotice] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);

  useEffect(() => {
    const requestId = ++listRequestRef.current;
    let active = true;
    const params: KnowledgeQueryParams = {
      scope: "project",
      projectId: project.projectId,
      page,
      pageSize: PAGE_SIZE,
      sortBy,
      sortDirection,
      includeArchived,
    };
    if (keyword) params.keyword = keyword;
    if (zone) params.zone = zone;
    if (assetType) params.assetType = assetType;
    if (assetStatus) params.assetStatus = assetStatus;
    if (confidentialityLevel) params.confidentialityLevel = confidentialityLevel;
    if (updatedFrom) params.updatedFrom = updatedFrom;
    if (updatedTo) params.updatedTo = updatedTo;

    setLoading(true);
    setListError(null);
    void fetchKnowledgePage(params)
      .then((nextResult) => {
        if (!active || requestId !== listRequestRef.current) return;
        setResult(nextResult);
        setHasLoaded(true);
      })
      .catch(() => {
        if (!active || requestId !== listRequestRef.current) return;
        setListError("项目知识暂时无法加载，请稍后重试。");
        setHasLoaded(true);
      })
      .finally(() => {
        if (active && requestId === listRequestRef.current) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [
    assetStatus,
    assetType,
    confidentialityLevel,
    includeArchived,
    keyword,
    listRetryKey,
    page,
    project.projectId,
    sortBy,
    sortDirection,
    updatedFrom,
    updatedTo,
    zone,
  ]);

  useEffect(() => {
    if (!qaOpen) return;
    const requestId = ++modelRequestRef.current;
    let active = true;
    setModelsState("loading");
    void fetchProjectQaModelOptions(project.projectId)
      .then((response) => {
        if (!active || requestId !== modelRequestRef.current) return;
        setModels(response.items);
        const defaultIndex = response.items.findIndex((item) => item.is_default);
        setSelectedModelIndex(
          response.items.length === 0 ? "" : String(defaultIndex >= 0 ? defaultIndex : 0),
        );
        setModelsState("ready");
      })
      .catch(() => {
        if (!active || requestId !== modelRequestRef.current) return;
        setModels([]);
        setSelectedModelIndex("");
        setModelsState("error");
      });
    return () => {
      active = false;
    };
  }, [modelsRetryKey, project.projectId, qaOpen]);

  useEffect(
    () => () => {
      listRequestRef.current += 1;
      modelRequestRef.current += 1;
      qaRequestRef.current += 1;
    },
    [],
  );

  const selectedModel = models[Number(selectedModelIndex)];
  const hasActiveFilters = Boolean(
    keyword ||
    zone ||
    assetType ||
    assetStatus ||
    confidentialityLevel ||
    updatedFrom ||
    updatedTo ||
    includeArchived ||
    sortBy !== "updated_at" ||
    sortDirection !== "desc",
  );

  const resetFilters = () => {
    setKeywordInput("");
    setKeyword("");
    setZone("");
    setAssetType("");
    setAssetStatus("");
    setConfidentialityLevel("");
    setUpdatedFrom("");
    setUpdatedTo("");
    setSortBy("updated_at");
    setSortDirection("desc");
    setIncludeArchived(false);
    setPage(1);
  };

  const submitKeyword = (event: FormEvent) => {
    event.preventDefault();
    setKeyword(keywordInput.trim());
    setPage(1);
  };

  const askQuestion = async () => {
    const question = qaInput.trim();
    if (!question || !selectedModel || qaState === "loading") return;
    const requestId = ++qaRequestRef.current;
    setQaQuestion(question);
    setQaResult(null);
    setQaState("loading");
    try {
      const response = await projectQa(project.projectId, {
        query: question,
        modelRef: selectedModel.model_ref,
      });
      if (requestId !== qaRequestRef.current) return;
      setQaResult(response);
      setQaState("idle");
    } catch {
      if (requestId !== qaRequestRef.current) return;
      setQaResult(null);
      setQaState("error");
    }
  };

  const handleQaKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      void askQuestion();
    }
  };

  const requestUpgrade = useCallback(
    async (assetId: string) => {
      if (project.projectRole !== "project_manager" || upgradeBusyId) return;
      setUpgradeBusyId(assetId);
      setUpgradeNotice(null);
      try {
        await requestCompanyUpgrade(project.projectId, assetId);
        setUpgradeNotice({ tone: "success", text: "公司资产升级申请已提交。" });
      } catch {
        setUpgradeNotice({ tone: "error", text: "升级申请提交失败，请稍后重试。" });
      } finally {
        setUpgradeBusyId(null);
      }
    },
    [project.projectId, project.projectRole, upgradeBusyId],
  );

  const columns = useMemo<Column<KnowledgeCardVM>[]>(
    () => [
      {
        key: "title",
        header: "知识名称",
        className: "pk-title-cell",
        render: (asset) => (
          <div className="pk-title">
            <FileText size={17} aria-hidden="true" />
            <strong title={asset.title}>{asset.title}</strong>
          </div>
        ),
      },
      { key: "zone", header: "所属区域", render: (asset) => safeZone(asset.zone) },
      { key: "type", header: "类型", render: (asset) => safeType(asset.assetType) },
      {
        key: "confidentiality",
        header: "保密级别",
        render: (asset) => (
          <span className="pk-confidentiality">
            {safeConfidentiality(asset.confidentialityLevel)}
          </span>
        ),
      },
      {
        key: "status",
        header: "状态",
        render: (asset) => (
          <StatusBadge
            label={safeStatus(asset.assetStatus)}
            tone={statusTones[asset.assetStatus] ?? "neutral"}
          />
        ),
      },
      {
        key: "updated",
        header: "最后更新",
        className: "pk-date-cell",
        render: (asset) =>
          asset.updatedAt ? <time dateTime={asset.updatedAt}>{asset.updatedAt}</time> : "未提供",
      },
      {
        key: "actions",
        header: "操作",
        className: "pk-action-cell",
        render: (asset) => (
          <div className="pk-row-actions">
            <button
              className="pk-detail-link"
              type="button"
              onClick={() => navigate(`/knowledge/${asset.id}`)}
            >
              查看详情
            </button>
            {project.projectRole === "project_manager" && asset.zone === "asset" && (
              <details className="pk-more-actions">
                <summary aria-label={`更多操作：${asset.title}`} title="更多操作">
                  <MoreHorizontal size={16} aria-hidden="true" />
                </summary>
                <button
                  type="button"
                  disabled={upgradeBusyId === asset.id}
                  onClick={() => void requestUpgrade(asset.id)}
                >
                  {upgradeBusyId === asset.id ? "提交中…" : "申请升格公司资产"}
                </button>
              </details>
            )}
          </div>
        ),
      },
    ],
    [navigate, project.projectRole, requestUpgrade, upgradeBusyId],
  );

  const totalPages = Math.max(1, Math.ceil(result.total / result.pageSize));
  const firstItem = result.total === 0 ? 0 : (result.page - 1) * result.pageSize + 1;
  const lastItem = Math.min(result.page * result.pageSize, result.total);
  const initialLoading = loading && !hasLoaded;

  return (
    <ProductPage className="pk-page">
      <PageHeader
        title="项目知识库"
        description={project.projectName}
        actions={
          <label className="pk-project-switcher">
            <span>切换项目</span>
            <select value={project.projectId} onChange={(event) => onSwitch(event.target.value)}>
              {projects.map((item) => (
                <option key={item.projectId} value={item.projectId}>
                  {item.projectName}
                </option>
              ))}
            </select>
          </label>
        }
      />

      <form className="pk-filter-form" onSubmit={submitKeyword}>
        <FilterBar
          ariaLabel="项目知识筛选"
          actions={
            <>
              <span className="pk-result-total">共 {result.total} 条</span>
              <button className="product-button is-primary is-small" type="submit">
                搜索
              </button>
              <button
                className="product-button is-ghost is-small"
                type="button"
                disabled={!hasActiveFilters && !keywordInput}
                onClick={resetFilters}
              >
                重置
              </button>
            </>
          }
        >
          <div className="pk-keyword-field">
            <Search size={16} aria-hidden="true" />
            <label className="sr-only" htmlFor="project-knowledge-keyword">
              关键词
            </label>
            <input
              id="project-knowledge-keyword"
              value={keywordInput}
              onChange={(event) => setKeywordInput(event.target.value)}
              placeholder="按标题或标签搜索"
            />
          </div>
          <label className="pk-select-field">
            <span className="sr-only">资料区域</span>
            <select
              aria-label="资料区域"
              value={zone}
              onChange={(event) => {
                setZone(event.target.value as KnowledgeZone | "");
                setPage(1);
              }}
            >
              <option value="">区域：全部</option>
              <option value="material">区域：资料区</option>
              <option value="asset">区域：资产区</option>
            </select>
          </label>
          <label className="pk-select-field">
            <span className="sr-only">资产类型</span>
            <select
              aria-label="资产类型"
              value={assetType}
              onChange={(event) => {
                setAssetType(event.target.value as AssetType | "");
                setPage(1);
              }}
            >
              <option value="">类型：全部</option>
              {ASSET_TYPES.map((value) => (
                <option key={value} value={value}>
                  类型：{assetTypeLabel[value]}
                </option>
              ))}
            </select>
          </label>
          <label className="pk-select-field">
            <span className="sr-only">资产状态</span>
            <select
              aria-label="资产状态"
              value={assetStatus}
              onChange={(event) => {
                setAssetStatus(event.target.value as AssetStatus | "");
                setPage(1);
              }}
            >
              <option value="">状态：全部</option>
              {ASSET_STATUSES.map((value) => (
                <option key={value} value={value}>
                  状态：{assetStatusLabel[value]}
                </option>
              ))}
            </select>
          </label>
          <label className="pk-select-field">
            <span className="sr-only">保密级别</span>
            <select
              aria-label="保密级别"
              value={confidentialityLevel}
              onChange={(event) => {
                setConfidentialityLevel(event.target.value as ConfidentialityLevel | "");
                setPage(1);
              }}
            >
              <option value="">保密：全部</option>
              {CONFIDENTIALITY_LEVELS.map((value) => (
                <option key={value} value={value}>
                  保密：{value}
                </option>
              ))}
            </select>
          </label>
          <details className="pk-more-filters">
            <summary>更多筛选</summary>
            <div className="pk-more-filter-panel">
              <label>
                <span>更新开始</span>
                <input
                  type="date"
                  value={updatedFrom}
                  onChange={(event) => {
                    setUpdatedFrom(event.target.value);
                    setPage(1);
                  }}
                />
              </label>
              <label>
                <span>更新结束</span>
                <input
                  type="date"
                  value={updatedTo}
                  onChange={(event) => {
                    setUpdatedTo(event.target.value);
                    setPage(1);
                  }}
                />
              </label>
              <label>
                <span>排序字段</span>
                <select
                  aria-label="排序字段"
                  value={sortBy}
                  onChange={(event) => {
                    setSortBy(event.target.value as KnowledgeSortField);
                    setPage(1);
                  }}
                >
                  <option value="updated_at">最后更新</option>
                  <option value="created_at">创建时间</option>
                  <option value="title">标题</option>
                  <option value="confidentiality_level">保密级别</option>
                  <option value="asset_status">状态</option>
                </select>
              </label>
              <label>
                <span>排序方向</span>
                <select
                  aria-label="排序方向"
                  value={sortDirection}
                  onChange={(event) => {
                    setSortDirection(event.target.value as SortDirection);
                    setPage(1);
                  }}
                >
                  <option value="desc">降序</option>
                  <option value="asc">升序</option>
                </select>
              </label>
              <label className="pk-archive-toggle">
                <input
                  type="checkbox"
                  checked={includeArchived}
                  onChange={(event) => {
                    setIncludeArchived(event.target.checked);
                    setPage(1);
                  }}
                />
                <span>包含归档</span>
              </label>
            </div>
          </details>
        </FilterBar>
      </form>

      <PageSection className="pk-list-section">
        {listError ? (
          <LoadingError
            error={listError}
            errorTitle="项目知识加载失败"
            errorDescription="项目知识暂时无法加载，请稍后重试。"
            onRetry={() => setListRetryKey((value) => value + 1)}
          />
        ) : (
          <>
            <div className="pk-table-status" role="status" aria-live="polite">
              {loading && hasLoaded ? "正在更新列表…" : ""}
            </div>
            {upgradeNotice && (
              <div className={`pk-upgrade-notice is-${upgradeNotice.tone}`} role="status">
                {upgradeNotice.text}
              </div>
            )}
            <DataTable
              columns={columns}
              rows={result.items}
              rowKey={(asset) => asset.id}
              loading={initialLoading}
              loadingText="正在加载项目知识…"
              emptyText={
                <EmptyState
                  title={hasActiveFilters ? "当前条件没有匹配内容" : "该项目暂无知识"}
                  description={
                    hasActiveFilters
                      ? "调整或清除筛选条件后重新查看。"
                      : "当前项目可访问的知识会显示在这里。"
                  }
                  action={
                    hasActiveFilters ? (
                      <button
                        className="product-button is-secondary is-small"
                        type="button"
                        onClick={resetFilters}
                      >
                        清除筛选
                      </button>
                    ) : undefined
                  }
                />
              }
              wrapClassName={`product-table-wrap pk-table-wrap ${loading ? "is-updating" : ""}`}
              tableClassName="product-data-table pk-table"
              ariaLabel="项目知识列表"
            />
            {hasLoaded && result.total > 0 && (
              <div className="pk-pagination" aria-label="项目知识分页">
                <span>
                  显示 {firstItem}-{lastItem} 条，共 {result.total} 条
                </span>
                <div className="pk-page-controls">
                  <button
                    type="button"
                    aria-label="上一页"
                    title="上一页"
                    disabled={loading || result.page <= 1}
                    onClick={() => setPage((value) => Math.max(1, value - 1))}
                  >
                    <ChevronLeft size={16} aria-hidden="true" />
                  </button>
                  {pageNumbers(result.page, totalPages).map((pageNumber) => (
                    <button
                      type="button"
                      key={pageNumber}
                      className={pageNumber === result.page ? "is-current" : ""}
                      aria-label={`第 ${pageNumber} 页`}
                      aria-current={pageNumber === result.page ? "page" : undefined}
                      disabled={loading}
                      onClick={() => setPage(pageNumber)}
                    >
                      {pageNumber}
                    </button>
                  ))}
                  <button
                    type="button"
                    aria-label="下一页"
                    title="下一页"
                    disabled={loading || !result.hasNext}
                    onClick={() => setPage((value) => value + 1)}
                  >
                    <ChevronRight size={16} aria-hidden="true" />
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </PageSection>

      <section className="pk-qa-section">
        <div className="pk-qa-disclosure">
          <button
            className="pk-qa-toggle"
            type="button"
            aria-expanded={qaOpen}
            onClick={() => setQaOpen((value) => !value)}
          >
            <span>
              <Bot size={17} aria-hidden="true" />
              项目问答
            </span>
            <small>基于当前项目知识提问</small>
          </button>
          {qaOpen && (
            <div className="pk-qa-body">
              {modelsState === "error" ? (
                <div className="pk-qa-state" role="status">
                  <span>问答模型暂时无法加载。</span>
                  <button
                    className="product-button is-secondary is-small"
                    type="button"
                    onClick={() => {
                      setModelsRetryKey((value) => value + 1);
                    }}
                  >
                    重试
                  </button>
                </div>
              ) : (
                <>
                  <div className="pk-qa-controls">
                    <label>
                      <span>问答模型</span>
                      <select
                        value={selectedModelIndex}
                        onChange={(event) => setSelectedModelIndex(event.target.value)}
                        disabled={modelsState === "loading" || models.length === 0}
                      >
                        {modelsState === "loading" && <option value="">正在加载…</option>}
                        {modelsState === "ready" && models.length === 0 && (
                          <option value="">暂无可用模型</option>
                        )}
                        {models.map((model, index) => (
                          <option key={index} value={String(index)}>
                            {model.display_name}
                          </option>
                        ))}
                      </select>
                    </label>
                    {modelsState === "ready" && models.length === 0 && (
                      <span className="pk-qa-state">当前项目暂无可用问答模型。</span>
                    )}
                  </div>
                  <textarea
                    value={qaInput}
                    onChange={(event) => setQaInput(event.target.value)}
                    onKeyDown={handleQaKeyDown}
                    placeholder="向当前项目知识提问…"
                    disabled={modelsState !== "ready" || models.length === 0}
                    rows={3}
                  />
                  <div className="pk-qa-submit-row">
                    <span>Ctrl / Command + Enter 发送</span>
                    <button
                      className="product-button is-primary is-small"
                      type="button"
                      disabled={!qaInput.trim() || !selectedModel || qaState === "loading"}
                      onClick={() => void askQuestion()}
                    >
                      {qaState === "loading" ? "正在回答…" : "提问"}
                    </button>
                  </div>
                  {qaState === "error" && (
                    <div className="pk-qa-error" role="alert">
                      问答暂时未完成，请稍后重试。
                    </div>
                  )}
                  {qaQuestion && (qaResult || qaState === "loading") && (
                    <div className="pk-conversation">
                      <div className="pk-question">
                        <span>你的问题</span>
                        <p>{qaQuestion}</p>
                      </div>
                      {qaResult && (
                        <div className="pk-answer">
                          <span>项目问答</span>
                          <p>{qaResult.response_text}</p>
                          {qaResult.citations.length > 0 && (
                            <div className="pk-citations">
                              <strong>引用</strong>
                              {qaResult.citations.map((citation, index) => (
                                <div
                                  key={`${citation.asset_title}-${citation.citation_order}-${index}`}
                                >
                                  <span>{citation.asset_title}</span>
                                  <small>{safeZone(citation.cited_zone)}</small>
                                  {citation.is_pending_review && <em>内容待审核，请谨慎参考</em>}
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </section>
    </ProductPage>
  );
}

export default function ProjectKnowledgePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { authMe, status } = useAuth();
  const projects = authMe?.projects ?? [];
  const routeProject = id ? (projects.find((project) => project.projectId === id) ?? null) : null;

  const switcher =
    projects.length > 0 ? (
      <label className="pk-project-switcher">
        <span>切换项目</span>
        <select value="" onChange={(event) => navigate(`/project/${event.target.value}/knowledge`)}>
          <option value="">选择可访问项目</option>
          {projects.map((project) => (
            <option key={project.projectId} value={project.projectId}>
              {project.projectName}
            </option>
          ))}
        </select>
      </label>
    ) : undefined;

  if (status === "loading") {
    return (
      <ProductPage className="pk-page">
        <LoadingError loading loadingTitle="正在加载项目…" />
      </ProductPage>
    );
  }

  if (!routeProject) {
    const noProjects = status === "authenticated" && projects.length === 0;
    return (
      <ProductPage className="pk-page">
        <PageHeader title="项目知识库" actions={switcher} />
        <PageSection>
          <EmptyState
            title={noProjects ? "暂无可访问项目" : "项目不可访问"}
            description={
              noProjects ? "当前账号没有有效的项目成员身份。" : "请从项目选择器进入有权访问的项目。"
            }
          />
        </PageSection>
      </ProductPage>
    );
  }

  return (
    <ProjectKnowledgeWorkspace
      key={routeProject.projectId}
      project={routeProject}
      projects={projects}
      onSwitch={(projectId) => navigate(`/project/${projectId}/knowledge`)}
    />
  );
}
