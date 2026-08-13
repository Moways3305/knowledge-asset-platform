import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  Building2,
  BriefcaseBusiness,
  ChevronLeft,
  ChevronRight,
  FileText,
  Folder,
  FolderTree,
  Search,
  Sparkles,
  Upload,
  UserRound,
} from "lucide-react";
import { Link, useSearchParams } from "react-router-dom";
import {
  fetchKnowledgeDetail,
  fetchKnowledgeDirectories,
  fetchKnowledgePage,
  requestOriginalAccess,
  searchKnowledge,
} from "../api/knowledge";
import { useAuth } from "../auth/AuthContext";
import { can } from "../auth/permissions";
import DataTable, { type Column } from "../components/DataTable";
import DetailDrawer from "../components/DetailDrawer";
import AccessExplanationDrawer, { accessLabel } from "../components/AccessExplanationDrawer";
import TaskModal from "../components/TaskModal";
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
  KnowledgeDirectoryDTO,
  KnowledgePageVM,
  KnowledgeQueryParams,
  KnowledgeScope,
} from "../types/knowledge";
import type { SearchResponseDTO } from "../types/search";
import { assetStatusLabel, assetTypeLabel, scopeLabels } from "../utils/knowledgeLabels";
import { knowledgeDetailSource } from "../routing/knowledgeDetailSource";
import "./KnowledgeListPage.css";

const PAGE_SIZE = 20;

const ASSET_TYPES: AssetType[] = [
  "methodology",
  "deliverable",
  "case",
  "template",
  "insight",
  "unclassified",
];
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

export default function KnowledgeListPage() {
  const { authMe, capabilities, status } = useAuth();
  const [searchParams] = useSearchParams();
  const initialScope = (searchParams.get("scope") as KnowledgeScope | null) ?? "";
  const [keywordInput, setKeywordInput] = useState(searchParams.get("keyword") ?? "");
  const [keyword, setKeyword] = useState(searchParams.get("keyword") ?? "");
  const [scope, setScope] = useState<KnowledgeScope | "">(initialScope);
  const [projectId, setProjectId] = useState(searchParams.get("project_id") ?? "");
  const [assetType, setAssetType] = useState<AssetType | "">(
    (searchParams.get("asset_type") as AssetType | null) ?? "",
  );
  const [assetStatus, setAssetStatus] = useState<AssetStatus | "">(
    (searchParams.get("asset_status") as AssetStatus | null) ?? "",
  );
  const [confidentialityLevel, setConfidentialityLevel] = useState<ConfidentialityLevel | "">(
    (searchParams.get("confidentiality") as ConfidentialityLevel | null) ?? "",
  );
  const [includeArchived, setIncludeArchived] = useState(searchParams.get("archived") === "1");
  const [directory, setDirectory] = useState<KnowledgeDirectoryDTO | null>(null);
  const [directoryItems, setDirectoryItems] = useState<KnowledgeDirectoryDTO[]>([]);
  const [directoryLoading, setDirectoryLoading] = useState(false);
  const [page, setPage] = useState(Math.max(1, Number(searchParams.get("page")) || 1));
  const [result, setResult] = useState<KnowledgePageVM>(emptyPage);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const requestRef = useRef(0);
  const restoredDirectoryRef = useRef(false);
  const tableShellRef = useRef<HTMLDivElement>(null);
  const topScrollerRef = useRef<HTMLDivElement>(null);
  const [tableOverflow, setTableOverflow] = useState(false);
  const [tableScrollWidth, setTableScrollWidth] = useState(0);
  const [tableAtEnd, setTableAtEnd] = useState(false);

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
  const [explainAsset, setExplainAsset] = useState<KnowledgeCardVM | KnowledgeDetailVM | null>(
    null,
  );
  const [requestAsset, setRequestAsset] = useState<KnowledgeCardVM | KnowledgeDetailVM | null>(
    null,
  );
  const [requestReason, setRequestReason] = useState("");
  const [requestError, setRequestError] = useState<string | null>(null);
  const [semanticQuery, setSemanticQuery] = useState("");
  const [semanticResult, setSemanticResult] = useState<SearchResponseDTO | null>(null);
  const [semanticBusy, setSemanticBusy] = useState(false);
  const [semanticError, setSemanticError] = useState<string | null>(null);
  const [globalSearchMode, setGlobalSearchMode] = useState(searchParams.get("search") === "global");
  const directoryKeyFromUrl = searchParams.get("directory_key");
  const visibleDirectoryItems = directoryItems.filter(
    (item) =>
      (!scope || item.scope === scope) &&
      (scope !== "project" || !validProjectId || item.project_id === validProjectId),
  );

  const returnQuery = new URLSearchParams();
  if (scope) returnQuery.set("scope", scope);
  if (validProjectId) returnQuery.set("project_id", validProjectId);
  if (directory) returnQuery.set("directory_key", directory.directory_key);
  if (keyword) returnQuery.set("keyword", keyword);
  if (assetType) returnQuery.set("asset_type", assetType);
  if (assetStatus) returnQuery.set("asset_status", assetStatus);
  if (confidentialityLevel) returnQuery.set("confidentiality", confidentialityLevel);
  if (includeArchived) returnQuery.set("archived", "1");
  if (page > 1) returnQuery.set("page", String(page));
  if (globalSearchMode) returnQuery.set("search", "global");
  const knowledgeReturnPath = `/knowledge${returnQuery.size ? `?${returnQuery}` : ""}`;
  const detailState = knowledgeDetailSource(
    knowledgeReturnPath,
    directory ? `返回${directory.name}` : "返回知识资产库",
    directory ? "directory" : "global-search",
  );

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
    const assetId = requestAsset?.id ?? summaryAssetId;
    if (!assetId) return;
    setRequestBusy(true);
    setSummaryError(null);
    setRequestError(null);
    try {
      const response = await requestOriginalAccess(assetId, requestReason.trim() || undefined);
      setRequestNote(
        response.status === "created"
          ? "已提交原文访问申请，请等待项目负责人审批。"
          : response.status === "pending_exists"
            ? "原文访问申请正在审批中。"
            : "原文访问已开放。",
      );
      setResult((current) => ({
        ...current,
        items: current.items.map((item) =>
          item.id !== assetId
            ? item
            : {
                ...item,
                access: {
                  ...item.access,
                  original: response.status === "already_granted" || item.access.original,
                  canRequestOriginal: false,
                  existingRequestStatus:
                    response.status === "created" || response.status === "pending_exists"
                      ? "pending"
                      : item.access.existingRequestStatus,
                },
              },
        ),
      }));
      if (summaryAssetId === assetId) setSummaryDetail(await fetchKnowledgeDetail(assetId));
      setRequestAsset(null);
      setRequestReason("");
    } catch {
      setRequestError("原文访问申请提交失败，请稍后重试。等待审批前不会开放原文。");
    } finally {
      setRequestBusy(false);
    }
  };

  const runSemanticSearch = async () => {
    if (!semanticQuery.trim()) return;
    setSemanticBusy(true);
    setSemanticError(null);
    try {
      setSemanticResult(
        await searchKnowledge({
          query: semanticQuery.trim(),
          scope: scope || "all",
          intent: "search",
          filters: {
            include_archived: includeArchived,
            directory_key: globalSearchMode ? undefined : directory?.directory_key,
            project_id: globalSearchMode ? undefined : directory?.project_id,
          },
        }),
      );
    } catch {
      setSemanticError("语义检索暂时无法完成，请重试。");
    } finally {
      setSemanticBusy(false);
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

    if (!directory) {
      setLoading(false);
      setError(null);
      setHasLoaded(false);
      setResult(emptyPage());
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
    params.scope = directory.scope;
    if (scope === "project" && validProjectId) params.projectId = validProjectId;
    if (assetType) params.assetType = assetType;
    if (assetStatus) params.assetStatus = assetStatus;
    if (confidentialityLevel) params.confidentialityLevel = confidentialityLevel;
    if (directory) {
      params.directoryKey = directory.directory_key;
      if (directory.project_id) params.projectId = directory.project_id;
    }

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
    directory,
  ]);

  useEffect(() => {
    if (!canLoadBusinessKnowledge) return;
    if (scope === "project" && !validProjectId) {
      setDirectoryItems([]);
      setDirectory(null);
      setDirectoryLoading(false);
      if (directoryKeyFromUrl) restoredDirectoryRef.current = true;
      return;
    }
    let active = true;
    setDirectoryLoading(true);
    void fetchKnowledgeDirectories(scope ? { scope, projectId: validProjectId || undefined } : {})
      .then((items) => {
        if (!active) return;
        setDirectoryItems(items);
        if (directoryKeyFromUrl && !restoredDirectoryRef.current) {
          const restored = items.find(
            (item) =>
              item.directory_key === directoryKeyFromUrl &&
              item.scope === scope &&
              (scope !== "project" || item.project_id === validProjectId),
          );
          if (restored) setDirectory(restored);
          restoredDirectoryRef.current = true;
        }
      })
      .finally(() => {
        if (active) setDirectoryLoading(false);
      });
    return () => {
      active = false;
    };
  }, [canLoadBusinessKnowledge, directoryKeyFromUrl, scope, validProjectId]);

  const resetFilters = () => {
    setKeywordInput("");
    setKeyword("");
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
    keyword || assetType || assetStatus || confidentialityLevel || includeArchived || false,
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
              {asset.access.crossProjectSummary ? (
                <button
                  className="kbl-title-link"
                  type="button"
                  title={asset.title}
                  aria-label={`查看《${asset.title}》安全摘要`}
                  onClick={() => openCrossProjectSummary(asset.id)}
                >
                  {asset.title}
                </button>
              ) : (
                <Link
                  className="kbl-title-link"
                  title={asset.title}
                  aria-label={`查看《${asset.title}》详情`}
                  to={`/knowledge/${asset.id}`}
                  state={detailState}
                >
                  {asset.title}
                </Link>
              )}
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
              {(!asset.access.original || asset.indexStatus !== "indexed") && (
                <button
                  type="button"
                  className="kbl-explain-link"
                  onClick={() => setExplainAsset(asset)}
                >
                  为什么？
                </button>
              )}
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
            <Link
              className="product-button is-secondary is-small"
              to={`/knowledge/${asset.id}`}
              state={detailState}
            >
              查看详情
            </Link>
          ),
      },
    ],
    [detailState],
  );

  const totalPages = Math.max(1, Math.ceil(result.total / result.pageSize));
  const firstItem = result.total === 0 ? 0 : (result.page - 1) * result.pageSize + 1;
  const lastItem = Math.min(result.page * result.pageSize, result.total);
  const initialLoading = status === "loading" || (loading && !hasLoaded);

  useEffect(() => {
    const shell = tableShellRef.current;
    const tableWrap = shell?.querySelector<HTMLElement>(".kbl-table-wrap");
    if (!shell || !tableWrap) return;
    const update = () => {
      const overflowing = tableWrap.scrollWidth > tableWrap.clientWidth + 2;
      setTableOverflow(overflowing);
      setTableScrollWidth(tableWrap.scrollWidth);
      setTableAtEnd(
        !overflowing || tableWrap.scrollLeft + tableWrap.clientWidth >= tableWrap.scrollWidth - 2,
      );
    };
    const syncTop = () => {
      if (topScrollerRef.current) topScrollerRef.current.scrollLeft = tableWrap.scrollLeft;
      update();
    };
    update();
    tableWrap.addEventListener("scroll", syncTop, { passive: true });
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => update());
    observer?.observe(tableWrap);
    observer?.observe(tableWrap.querySelector("table") ?? tableWrap);
    window.addEventListener("resize", update);
    return () => {
      tableWrap.removeEventListener("scroll", syncTop);
      observer?.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [initialLoading, result.items]);

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
          <nav className="kbl-breadcrumbs" aria-label="知识资产目录路径">
            <button
              type="button"
              onClick={() => {
                setScope("");
                setProjectId("");
                setDirectory(null);
                setGlobalSearchMode(false);
                setPage(1);
              }}
              aria-current={!scope && !globalSearchMode ? "page" : undefined}
            >
              知识资产库
            </button>
            {scope && (
              <>
                <ChevronRight size={14} aria-hidden="true" />
                <button
                  type="button"
                  aria-current={
                    !directory && !(scope === "project" && validProjectId) ? "page" : undefined
                  }
                  onClick={() => {
                    setProjectId("");
                    setDirectory(null);
                    setGlobalSearchMode(false);
                    setPage(1);
                  }}
                >
                  {scope === "company" ? "公司库" : scope === "project" ? "项目库" : "个人库"}
                </button>
              </>
            )}
            {scope === "project" && validProjectId && (
              <>
                <ChevronRight size={14} aria-hidden="true" />
                <button
                  type="button"
                  aria-current={!directory ? "page" : undefined}
                  onClick={() => {
                    setDirectory(null);
                    setPage(1);
                  }}
                >
                  {projects.find((item) => item.projectId === validProjectId)?.projectName}
                </button>
              </>
            )}
            {directory && (
              <>
                <ChevronRight size={14} aria-hidden="true" />
                <span aria-current="page">{directory.name}</span>
              </>
            )}
            {globalSearchMode && (
              <>
                <ChevronRight size={14} aria-hidden="true" />
                <span aria-current="page">全库搜索</span>
              </>
            )}
          </nav>

          {!directory && !globalSearchMode && (
            <PageSection className="kbl-folder-section">
              <div className="kbl-folder-heading">
                <div>
                  <span>{scope ? "选择下一级" : "从资料库开始"}</span>
                  <h2>
                    {!scope
                      ? "浏览知识目录"
                      : scope === "project" && !validProjectId
                        ? "选择项目"
                        : "选择标准目录"}
                  </h2>
                </div>
                <FolderTree size={24} aria-hidden="true" />
              </div>
              {directoryLoading ? (
                <p className="kbl-folder-loading" role="status">
                  正在读取可进入的目录…
                </p>
              ) : (
                <div className="kbl-folder-grid">
                  {!scope && (
                    <>
                      <button type="button" onClick={() => setScope("company")}>
                        <Building2 aria-hidden="true" />
                        <strong>公司库</strong>
                        <span>公司级方法、案例与标准资产</span>
                      </button>
                      {projects.length > 0 && (
                        <button type="button" onClick={() => setScope("project")}>
                          <BriefcaseBusiness aria-hidden="true" />
                          <strong>项目库</strong>
                          <span>按所属项目进入交付资料目录</span>
                        </button>
                      )}
                      <button type="button" onClick={() => setScope("personal")}>
                        <UserRound aria-hidden="true" />
                        <strong>个人库</strong>
                        <span>个人学习、项目资料与待处理内容</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setScope("");
                          setProjectId("");
                          setGlobalSearchMode(true);
                        }}
                      >
                        <Search aria-hidden="true" />
                        <strong>全库搜索</strong>
                        <span>主动跨目录检索当前身份可见内容</span>
                      </button>
                    </>
                  )}
                  {scope === "project" &&
                    !validProjectId &&
                    projects.map((project) => (
                      <button
                        type="button"
                        key={project.projectId}
                        onClick={() => setProjectId(project.projectId)}
                      >
                        <Folder aria-hidden="true" />
                        <strong>{project.projectName}</strong>
                        <span>进入项目标准目录</span>
                      </button>
                    ))}
                  {scope &&
                    (scope !== "project" || validProjectId) &&
                    visibleDirectoryItems.map((item) => (
                      <button
                        type="button"
                        key={`${item.directory_key}-${item.project_id ?? "global"}`}
                        onClick={() => {
                          setDirectory(item);
                          setPage(1);
                        }}
                      >
                        <Folder aria-hidden="true" />
                        <strong>{item.name}</strong>
                        <span>{item.description || "进入此目录查看资料"}</span>
                      </button>
                    ))}
                </div>
              )}
            </PageSection>
          )}

          {directory && (
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
          )}

          {requestNote && (
            <div className="kbl-request-feedback" role="status">
              <span>{requestNote}</span>
              <Link to="/original-access?box=mine">查看申请进度</Link>
            </div>
          )}

          {directory && (
            <PageSection className="kbl-list-section">
              <div className="kbl-scope-summary" aria-label="当前生效范围与筛选">
                <strong>当前浏览范围</strong>
                <span>{scope ? scopeLabels[scope] : "全部可见范围"}</span>
                {validProjectId && (
                  <span>
                    {projects.find((item) => item.projectId === validProjectId)?.projectName}
                  </span>
                )}
                {keyword && <span>关键词：{keyword}</span>}
                {assetType && <span>类型：{assetTypeLabel[assetType]}</span>}
                {assetStatus && <span>状态：{assetStatusLabel[assetStatus]}</span>}
                {confidentialityLevel && <span>保密：{confidentialityLevel}</span>}
                {includeArchived && <span>包含归档</span>}
                {!hasActiveFilters && <small>未添加额外筛选</small>}
              </div>
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
                  <div
                    className={`kbl-table-shell ${tableOverflow && !tableAtEnd ? "has-more" : ""}`}
                    ref={tableShellRef}
                  >
                    {tableOverflow && (
                      <div className="kbl-scroll-guide">
                        <span>向右滚动查看更多列</span>
                        <div
                          className="kbl-top-scroll"
                          ref={topScrollerRef}
                          aria-label="知识资产表横向滚动"
                          tabIndex={0}
                          onScroll={(event) => {
                            const tableWrap =
                              tableShellRef.current?.querySelector<HTMLElement>(".kbl-table-wrap");
                            if (tableWrap) tableWrap.scrollLeft = event.currentTarget.scrollLeft;
                          }}
                        >
                          <div style={{ width: tableScrollWidth }} />
                        </div>
                      </div>
                    )}
                    <DataTable
                      columns={columns}
                      rows={result.items}
                      rowKey={(asset) => asset.id}
                      loading={initialLoading}
                      loadingText="正在加载知识资产…"
                      emptyText={
                        <EmptyState
                          title={
                            hasActiveFilters ? "当前条件没有匹配资料" : "当前身份暂无可浏览资料"
                          }
                          description={
                            hasActiveFilters
                              ? "仅表示当前可见范围内没有匹配项；不会确认不可见资料是否存在。"
                              : "部分资料可能因项目或保密权限不在当前可见范围内。"
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
                  </div>

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
          )}
          {(directory || globalSearchMode) && (
            <PageSection className="kbl-semantic-section">
              <div className="kbl-semantic-heading">
                <div>
                  <span>{globalSearchMode ? "跨目录任务" : "当前目录内"}</span>
                  <h2>{globalSearchMode ? "全库搜索" : "在当前目录检索"}</h2>
                  <p>
                    {globalSearchMode
                      ? "仅检索当前身份有权发现的资料；返回目录浏览时不会保留跨目录范围。"
                      : "携带当前目录和项目范围调用安全检索 API，不会越过当前文件夹。"}
                  </p>
                </div>
                <Sparkles aria-hidden="true" />
              </div>
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void runSemanticSearch();
                }}
                className="kbl-semantic-form"
              >
                <label htmlFor="semantic-query">用自然语言描述要找的内容</label>
                <div>
                  <input
                    id="semantic-query"
                    value={semanticQuery}
                    onChange={(event) => setSemanticQuery(event.target.value)}
                    placeholder="例如：如何组织项目复盘访谈？"
                  />
                  <button type="submit" disabled={semanticBusy || !semanticQuery.trim()}>
                    {semanticBusy ? "检索中…" : "语义检索"}
                  </button>
                </div>
              </form>
              {semanticError && (
                <div role="alert" className="kbl-drawer-message is-error">
                  {semanticError}{" "}
                  <button type="button" onClick={() => void runSemanticSearch()}>
                    重试
                  </button>
                </div>
              )}
              {semanticResult &&
                (semanticResult.cards.length || semanticResult.answer ? (
                  <div className="kbl-semantic-results">
                    {semanticResult.answer && (
                      <article className="kbl-semantic-answer">
                        <span>安全回答</span>
                        <p>{semanticResult.answer}</p>
                      </article>
                    )}
                    {semanticResult.cards.map((card) => (
                      <article key={card.asset_id}>
                        <h3>
                          <Link
                            to={`/knowledge/${encodeURIComponent(card.asset_id)}`}
                            state={detailState}
                          >
                            {card.title}
                          </Link>
                        </h3>
                        <p>{card.one_liner || card.detailed || "暂无可展示的安全摘要"}</p>
                        <span>相关度 {Math.round(card.relevance_score * 100)}%</span>
                      </article>
                    ))}
                    {semanticResult.citations.length > 0 && (
                      <section className="kbl-semantic-citations" aria-label="安全引用">
                        <h3>引用</h3>
                        <ol>
                          {semanticResult.citations.map((citation) => (
                            <li key={`${citation.asset_id}-${citation.citation_order}`}>
                              <strong>{citation.asset_title}</strong>
                              {citation.snippet && <p>{citation.snippet}</p>}
                              <small>
                                {citation.used_access_layer === "original"
                                  ? "授权原文证据"
                                  : "安全摘要证据"}
                              </small>
                            </li>
                          ))}
                        </ol>
                      </section>
                    )}
                  </div>
                ) : (
                  <EmptyState
                    title="当前检索没有匹配结果"
                    description="这只表示当前身份和检索范围内没有可返回结果，不代表系统中不存在相关资料。"
                  />
                ))}
            </PageSection>
          )}
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
              <Link
                className="product-button is-primary"
                to={`/knowledge/${summaryDetail.id}`}
                state={detailState}
              >
                原文访问已开放，查看详情
              </Link>
            ) : summaryDetail.access.existingRequestStatus === "pending" ? (
              <Link className="product-button is-secondary" to="/original-access?box=mine">
                原文申请审批中
              </Link>
            ) : summaryDetail.access.canRequestOriginal ? (
              <button
                className="product-button is-primary"
                type="button"
                disabled={requestBusy}
                onClick={() => {
                  setRequestAsset(summaryDetail);
                  setRequestReason("");
                }}
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
            <section className="kbl-summary-core" aria-labelledby="summary-core-title">
              <h3 id="summary-core-title">核心信息</h3>
              <dl>
                <div>
                  <dt>资料范围</dt>
                  <dd>项目知识</dd>
                </div>
                <div>
                  <dt>来源项目</dt>
                  <dd>{summaryDetail.projectName || "暂无"}</dd>
                </div>
                <div>
                  <dt>资料类型</dt>
                  <dd>{assetTypeLabel[summaryDetail.assetType] ?? "暂无"}</dd>
                </div>
                <div>
                  <dt>目录类别</dt>
                  <dd>{summaryDetail.categoryPath || "暂无"}</dd>
                </div>
                <div>
                  <dt>保密等级</dt>
                  <dd>{confidentialityLabels[summaryDetail.confidentialityLevel]}</dd>
                </div>
                <div>
                  <dt>当前状态</dt>
                  <dd>{assetStatusLabel[summaryDetail.assetStatus] ?? "暂无"}</dd>
                </div>
                <div>
                  <dt>规范名版本</dt>
                  <dd>{summaryDetail.safeVersion || "暂无"}</dd>
                </div>
                <div>
                  <dt>更新时间</dt>
                  <dd>{summaryDetail.updatedAt || "暂无"}</dd>
                </div>
                <div>
                  <dt>问答 / 检索</dt>
                  <dd>
                    {summaryDetail.qaAvailable == null && summaryDetail.retrievalAvailable == null
                      ? "暂无"
                      : `${summaryDetail.qaAvailable ? "问答可用" : "问答不可用"} · ${summaryDetail.retrievalAvailable ? "检索可用" : "检索不可用"}`}
                    {(summaryDetail.qaAvailable === false ||
                      summaryDetail.retrievalAvailable === false) && (
                      <button
                        className="kbl-explain-link"
                        type="button"
                        onClick={() => setExplainAsset(summaryDetail)}
                      >
                        为什么？
                      </button>
                    )}
                  </dd>
                </div>
                <div>
                  <dt>维护人</dt>
                  <dd>{summaryDetail.maintainerName || "暂无"}</dd>
                </div>
              </dl>
            </section>
            {summaryDetail.tags.length > 0 && (
              <div className="kbl-summary-drawer-tags" aria-label="知识标签">
                {summaryDetail.tags.map((tag) => (
                  <span key={tag}>{tag}</span>
                ))}
              </div>
            )}
          </div>
        ) : null}
      </DetailDrawer>
      <AccessExplanationDrawer
        open={explainAsset !== null}
        asset={explainAsset}
        capabilities={capabilities}
        onClose={() => setExplainAsset(null)}
        onRequest={() => {
          setRequestError(null);
          setRequestAsset(explainAsset);
          setExplainAsset(null);
        }}
      />
      <TaskModal
        open={requestAsset !== null}
        size="small"
        title="申请原文"
        description="申请当前资料的受控原文；提交前不会改变资料、授权或审批状态。"
        busy={requestBusy}
        onClose={() => {
          if (!requestBusy) {
            setRequestAsset(null);
            setRequestReason("");
            setRequestError(null);
          }
        }}
        footer={
          <>
            <button
              type="button"
              className="product-button is-secondary"
              disabled={requestBusy}
              onClick={() => {
                setRequestAsset(null);
                setRequestReason("");
                setRequestError(null);
              }}
            >
              取消
            </button>
            <button
              type="button"
              className="product-button is-primary"
              disabled={requestBusy}
              onClick={() => void submitOriginalRequest()}
            >
              {requestBusy ? "提交中…" : "提交申请"}
            </button>
          </>
        }
      >
        <label className="kbl-request-field">
          <span>申请理由（可选）</span>
          <textarea
            rows={4}
            value={requestReason}
            onChange={(event) => setRequestReason(event.target.value)}
            placeholder="说明需要使用原文的业务场景"
          />
        </label>
        {requestError && (
          <p className="kbl-request-error" role="alert">
            {requestError}
          </p>
        )}
      </TaskModal>
    </ProductPage>
  );
}
