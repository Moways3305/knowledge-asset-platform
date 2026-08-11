import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { ChevronLeft, ChevronRight, FileText, Search, Upload } from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import { fetchKnowledgeDetail, fetchKnowledgePage, requestOriginalAccess } from "../api/knowledge";
import { useAuth } from "../auth/AuthContext";
import { can } from "../auth/permissions";
import DataTable, { type Column } from "../components/DataTable";
import DetailDrawer from "../components/DetailDrawer";
import LoadingError from "../components/LoadingError";
import {
  EmptyState,
  FilterBar,
  PageHeader,
  PageSection,
  ProductPage,
} from "../components/ProductLayout";
import StatusBadge from "../components/StatusBadge";
import type {
  AssetStatus,
  AssetType,
  ConfidentialityLevel,
  KnowledgeCardVM,
  KnowledgeDetailVM,
  KnowledgePageVM,
  KnowledgeQueryParams,
  KnowledgeScope,
} from "../types/knowledge";
import { assetStatusLabel, assetTypeLabel, scopeLabels } from "../utils/knowledgeLabels";
import "./KnowledgeListPage.css";

const PAGE_SIZE = 20;

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

function accessLabel(asset: KnowledgeCardVM): string {
  if (asset.access.crossProjectSummary) {
    return asset.access.original ? "其他项目 · 原文已授权" : "其他项目 · 摘要可见";
  }
  if (!asset.access.summary) return "仅可发现";
  if (!asset.access.original) return "可查看摘要，原文受限";
  return "可查看摘要与原文";
}

const SCOPE_TABS: Array<{ value: KnowledgeScope | ""; label: string }> = [
  { value: "", label: "全部" },
  { value: "company", label: "公司" },
  { value: "personal", label: "个人" },
  { value: "project", label: "项目" },
];

export default function KnowledgeListPage() {
  const { authMe, capabilities, status } = useAuth();
  const [searchParams] = useSearchParams();
  const initialScope = (searchParams.get("scope") as KnowledgeScope | null) ?? "";
  const [keywordInput, setKeywordInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [scope, setScope] = useState<KnowledgeScope | "">(initialScope);
  const [projectId, setProjectId] = useState("");
  const [assetType, setAssetType] = useState<AssetType | "">("");
  const [assetStatus, setAssetStatus] = useState<AssetStatus | "">("");
  const [confidentialityLevel, setConfidentialityLevel] = useState<ConfidentialityLevel | "">("");
  const [includeArchived, setIncludeArchived] = useState(false);
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<KnowledgePageVM>(emptyPage);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const requestRef = useRef(0);

  const projects = authMe?.projects ?? [];
  const validProjectId = projects.some((project) => project.projectId === projectId)
    ? projectId
    : "";
  const canLoadBusinessKnowledge = status === "authenticated" && capabilities.isBusinessUser;
  const [summaryAssetId, setSummaryAssetId] = useState<string | null>(null);
  const [summaryDetail, setSummaryDetail] = useState<KnowledgeDetailVM | null>(null);
  const [summaryLoading, setSummaryLoading] = useState(false);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [requestBusy, setRequestBusy] = useState(false);
  const [requestNote, setRequestNote] = useState<string | null>(null);

  const openCrossProjectSummary = (assetId: string) => {
    setSummaryAssetId(assetId);
    setSummaryDetail(null);
    setSummaryError(null);
    setRequestNote(null);
    setSummaryLoading(true);
    void fetchKnowledgeDetail(assetId)
      .then(setSummaryDetail)
      .catch(() => setSummaryError("摘要暂时无法加载，请稍后重试。"))
      .finally(() => setSummaryLoading(false));
  };

  const closeCrossProjectSummary = () => {
    if (requestBusy) return;
    setSummaryAssetId(null);
    setSummaryDetail(null);
    setSummaryError(null);
    setRequestNote(null);
  };

  const submitOriginalRequest = async () => {
    if (!summaryAssetId) return;
    setRequestBusy(true);
    setSummaryError(null);
    try {
      const response = await requestOriginalAccess(summaryAssetId);
      setRequestNote(
        response.status === "created"
          ? "已提交原文访问申请，请等待项目负责人审批。"
          : response.status === "pending_exists"
            ? "原文访问申请正在审批中。"
            : "原文访问已开放。",
      );
      setSummaryDetail(await fetchKnowledgeDetail(summaryAssetId));
    } catch {
      setSummaryError("原文访问申请提交失败，请稍后重试。等待审批前不会开放原文。");
    } finally {
      setRequestBusy(false);
    }
  };

  useEffect(() => {
    const requestId = ++requestRef.current;
    let active = true;
    if (!canLoadBusinessKnowledge) {
      setLoading(false);
      setError(null);
      return;
    }

    const params: KnowledgeQueryParams = {
      page,
      pageSize: PAGE_SIZE,
      sortBy: "updated_at",
      sortDirection: "desc",
      includeArchived,
    };
    if (keyword) params.keyword = keyword;
    if (scope) params.scope = scope;
    if (scope === "project" && validProjectId) params.projectId = validProjectId;
    if (assetType) params.assetType = assetType;
    if (assetStatus) params.assetStatus = assetStatus;
    if (confidentialityLevel) params.confidentialityLevel = confidentialityLevel;

    setLoading(true);
    setError(null);
    void fetchKnowledgePage(params)
      .then((nextResult) => {
        if (!active || requestId !== requestRef.current) return;
        setResult(nextResult);
        setHasLoaded(true);
      })
      .catch(() => {
        if (!active || requestId !== requestRef.current) return;
        setError("知识资产暂时无法加载，请稍后重试。");
        setHasLoaded(true);
      })
      .finally(() => {
        if (active && requestId === requestRef.current) setLoading(false);
      });

    return () => {
      active = false;
    };
  }, [
    assetStatus,
    assetType,
    canLoadBusinessKnowledge,
    confidentialityLevel,
    includeArchived,
    keyword,
    page,
    retryKey,
    scope,
    validProjectId,
  ]);

  const resetFilters = () => {
    setKeywordInput("");
    setKeyword("");
    setScope("");
    setProjectId("");
    setAssetType("");
    setAssetStatus("");
    setConfidentialityLevel("");
    setIncludeArchived(false);
    setPage(1);
  };

  const submitKeyword = (event: FormEvent) => {
    event.preventDefault();
    setKeyword(keywordInput.trim());
    setPage(1);
  };

  const clearKeyword = () => {
    setKeywordInput("");
    setKeyword("");
    setPage(1);
  };

  const hasActiveFilters = Boolean(
    keyword ||
    scope ||
    validProjectId ||
    assetType ||
    assetStatus ||
    confidentialityLevel ||
    includeArchived,
  );

  const columns = useMemo<Column<KnowledgeCardVM>[]>(
    () => [
      {
        key: "asset",
        header: "资产名称与安全摘要",
        className: "kbl-asset-cell",
        render: (asset) => (
          <div className="kbl-asset">
            <FileText size={17} aria-hidden="true" />
            <div>
              <strong title={asset.title}>{asset.title}</strong>
              {asset.canonicalName && (
                <small title={asset.canonicalName}>{asset.canonicalName}</small>
              )}
              {asset.access.summary && asset.summary ? (
                <p>{asset.summary}</p>
              ) : asset.access.crossProjectSummary && asset.access.summary ? (
                <p className="kbl-summary-muted">暂无可共享摘要</p>
              ) : (
                <p className="kbl-summary-muted">当前身份仅可发现此资产</p>
              )}
              <span className={`kbl-access ${asset.access.original ? "is-full" : "is-limited"}`}>
                {accessLabel(asset)}
              </span>
            </div>
          </div>
        ),
      },
      {
        key: "source",
        header: "来源项目 / 所属范围",
        className: "kbl-source-cell",
        render: (asset) => (
          <div>
            <strong>
              {asset.scope === "project"
                ? asset.projectName || "项目知识"
                : scopeLabels[asset.scope]}
            </strong>
            {asset.scope === "project" && <span>{scopeLabels.project}</span>}
          </div>
        ),
      },
      {
        key: "type",
        header: "类型",
        render: (asset) => assetTypeLabel[asset.assetType] ?? asset.assetType,
      },
      {
        key: "status",
        header: "状态",
        render: (asset) => (
          <StatusBadge
            label={assetStatusLabel[asset.assetStatus] ?? asset.assetStatus}
            tone={statusTones[asset.assetStatus] ?? "neutral"}
          />
        ),
      },
      {
        key: "confidentiality",
        header: "保密等级",
        render: (asset) => (
          <span className={`kbl-confidentiality is-${asset.confidentialityLevel}`}>
            {confidentialityLabels[asset.confidentialityLevel] ?? asset.confidentialityLevel}
          </span>
        ),
      },
      {
        key: "updated",
        header: "更新时间",
        className: "kbl-date-cell",
        render: (asset) => <time dateTime={asset.updatedAt}>{asset.updatedAt || "未提供"}</time>,
      },
      {
        key: "actions",
        header: "操作",
        className: "kbl-action-cell",
        render: (asset) =>
          asset.access.crossProjectSummary ? (
            <button
              className="product-button is-secondary is-small"
              type="button"
              onClick={() => openCrossProjectSummary(asset.id)}
            >
              查看摘要
            </button>
          ) : (
            <Link className="product-button is-secondary is-small" to={`/knowledge/${asset.id}`}>
              查看详情
            </Link>
          ),
      },
    ],
    [],
  );

  const totalPages = Math.max(1, Math.ceil(result.total / result.pageSize));
  const firstItem = result.total === 0 ? 0 : (result.page - 1) * result.pageSize + 1;
  const lastItem = Math.min(result.page * result.pageSize, result.total);
  const initialLoading = status === "loading" || (loading && !hasLoaded);

  return (
    <ProductPage className="kbl-page">
      <PageHeader
        title="知识资产库"
        description="浏览本项目知识与其他项目可共享摘要；跨项目原文仍需逐项申请。"
        actions={
          can.viewUpload(capabilities) ? (
            <Link className="product-button is-primary" to="/upload">
              <Upload size={16} aria-hidden="true" />
              上传资产
            </Link>
          ) : undefined
        }
      />

      {status !== "loading" && !capabilities.isBusinessUser ? (
        <PageSection>
          <LoadingError
            forbidden
            forbiddenTitle="当前身份不浏览业务知识"
            forbiddenDesc="系统管理身份仅使用运营管理入口，不显示任何业务知识资产或资产数量。"
          />
        </PageSection>
      ) : (
        <>
          <div className="kbl-scope-tabs" role="tablist" aria-label="知识范围">
            {SCOPE_TABS.map((tab) => {
              const active = scope === tab.value;
              return (
                <button
                  key={tab.value || "all"}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className={`kbl-scope-tab ${active ? "is-active" : ""}`}
                  onClick={() => {
                    setScope(tab.value);
                    setProjectId("");
                    setPage(1);
                  }}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>

          <form className="kbl-filter-form" onSubmit={submitKeyword}>
            <FilterBar
              ariaLabel="知识资产筛选"
              actions={
                <>
                  <button className="product-button is-primary is-small" type="submit">
                    搜索
                  </button>
                  {(keywordInput || keyword) && (
                    <button
                      className="product-button is-secondary is-small"
                      type="button"
                      onClick={clearKeyword}
                    >
                      清除
                    </button>
                  )}
                  <button
                    className="product-button is-ghost is-small"
                    type="button"
                    disabled={!hasActiveFilters}
                    onClick={resetFilters}
                  >
                    重置
                  </button>
                </>
              }
            >
              <div className="kbl-keyword-field">
                <Search size={16} aria-hidden="true" />
                <label className="sr-only" htmlFor="knowledge-keyword">
                  关键词
                </label>
                <input
                  id="knowledge-keyword"
                  value={keywordInput}
                  onChange={(event) => setKeywordInput(event.target.value)}
                  placeholder="按标题或标签搜索"
                />
              </div>

              {scope === "project" && projects.length > 0 && (
                <label className="kbl-select-field is-project">
                  <span className="sr-only">项目</span>
                  <select
                    aria-label="项目"
                    value={validProjectId}
                    onChange={(event) => {
                      setProjectId(event.target.value);
                      setPage(1);
                    }}
                  >
                    <option value="">项目：全部所属项目</option>
                    {projects.map((project) => (
                      <option key={project.projectId} value={project.projectId}>
                        {project.projectName}
                      </option>
                    ))}
                  </select>
                </label>
              )}

              <label className="kbl-select-field">
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

              <label className="kbl-select-field">
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

              <label className="kbl-select-field">
                <span className="sr-only">保密等级</span>
                <select
                  aria-label="保密等级"
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

              <label className="kbl-archive-toggle">
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
            </FilterBar>
          </form>

          <PageSection className="kbl-list-section">
            {error ? (
              <LoadingError
                error={error}
                errorTitle="知识资产加载失败"
                onRetry={() => setRetryKey((value) => value + 1)}
              />
            ) : (
              <>
                <div className="kbl-table-status" role="status" aria-live="polite">
                  {loading && hasLoaded ? "正在更新列表…" : ""}
                </div>
                <DataTable
                  columns={columns}
                  rows={result.items}
                  rowKey={(asset) => asset.id}
                  loading={initialLoading}
                  loadingText="正在加载知识资产…"
                  emptyText={
                    <EmptyState
                      title={hasActiveFilters ? "当前条件没有匹配资产" : "暂无可浏览的知识资产"}
                      description={
                        hasActiveFilters
                          ? "调整或清除筛选条件后重新查看。"
                          : "当前身份可访问的知识资产会显示在这里。"
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
                  wrapClassName={`product-table-wrap kbl-table-wrap ${loading ? "is-updating" : ""}`}
                  tableClassName="product-data-table kbl-table"
                  ariaLabel="知识资产列表"
                />

                {hasLoaded && result.total > 0 && (
                  <div className="kbl-pagination" aria-label="知识资产分页">
                    <span>
                      显示 {firstItem}-{lastItem} 条，共 {result.total} 条
                    </span>
                    <div className="kbl-page-controls">
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
        </>
      )}

      <DetailDrawer
        open={summaryAssetId !== null}
        title={summaryDetail?.title ?? "跨项目知识摘要"}
        description="其他项目 · 摘要可见。此处不授予项目空间权限，也不展示原文或项目治理信息。"
        busy={requestBusy}
        onClose={closeCrossProjectSummary}
        footer={
          summaryDetail ? (
            summaryDetail.access.original ? (
              <Link className="product-button is-primary" to={`/knowledge/${summaryDetail.id}`}>
                原文访问已开放，查看详情
              </Link>
            ) : summaryDetail.access.existingRequestStatus === "pending" ? (
              <button className="product-button is-secondary" type="button" disabled>
                原文申请审批中
              </button>
            ) : summaryDetail.access.canRequestOriginal ? (
              <button
                className="product-button is-primary"
                type="button"
                disabled={requestBusy}
                onClick={() => void submitOriginalRequest()}
              >
                {requestBusy ? "提交中…" : "申请原文"}
              </button>
            ) : undefined
          ) : undefined
        }
      >
        {summaryLoading ? (
          <p role="status">正在加载安全摘要…</p>
        ) : summaryError ? (
          <div className="kbl-drawer-message is-error" role="alert">
            {summaryError}
          </div>
        ) : summaryDetail ? (
          <div className="kbl-summary-drawer">
            <div className="kbl-summary-drawer-meta">
              <span>{summaryDetail.projectName || "其他项目"}</span>
              <span>{confidentialityLabels[summaryDetail.confidentialityLevel]}</span>
            </div>
            {summaryDetail.detailed || summaryDetail.oneLiner ? (
              <p>{summaryDetail.detailed || summaryDetail.oneLiner}</p>
            ) : (
              <EmptyState
                title="暂无可共享摘要"
                description="安全摘要尚未生成。你仍可申请原文，审批通过后再查看受控内容。"
              />
            )}
            {summaryDetail.tags.length > 0 && (
              <div className="kbl-summary-drawer-tags" aria-label="知识标签">
                {summaryDetail.tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
            )}
            {requestNote && (
              <div className="kbl-drawer-message is-success" role="status">
                {requestNote}
              </div>
            )}
          </div>
        ) : null}
      </DetailDrawer>
    </ProductPage>
  );
}
