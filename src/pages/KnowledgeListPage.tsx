import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import {
  Building2,
  BriefcaseBusiness,
  ChevronRight,
  FileText,
  Folder,
  Search,
  Upload,
  UserRound,
} from "lucide-react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../api/http";
import {
  fetchKnowledgeDetail,
  fetchKnowledgeDirectories,
  fetchKnowledgeLibraryProjects,
  fetchKnowledgePage,
  requestOriginalAccess,
  searchKnowledge,
} from "../api/knowledge";
import { useAuth } from "../auth/AuthContext";
import { can } from "../auth/permissions";
import { ActionGroup } from "../components/ActionLayout";
import Button from "../components/Button";
import DataTable, { type Column } from "../components/DataTable";
import DetailDrawer from "../components/DetailDrawer";
import KnowledgeMetadataEditor from "../components/KnowledgeMetadataEditor";
import CreateKnowledgeDirectoryButton from "../components/CreateKnowledgeDirectoryButton";
import { summaryPendingLabel } from "../components/knowledgeSummaryState";
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
import PagePagination from "../components/PagePagination";
import type {
  AssetStatus,
  ConfidentialityLevel,
  KnowledgeCardVM,
  KnowledgeDetailVM,
  KnowledgeDirectoryDTO,
  KnowledgeLibraryProjectDTO,
  KnowledgePageVM,
  KnowledgeQueryParams,
  KnowledgeScope,
} from "../types/knowledge";
import type { SearchResponseDTO } from "../types/search";
import { assetStatusLabel, scopeLabels } from "../utils/knowledgeLabels";
import { knowledgeDetailSource } from "../routing/knowledgeDetailSource";
import "./KnowledgeListPage.css";

const PAGE_SIZE = 20;

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

export default function KnowledgeListPage() {
  const { capabilities, status, authMe } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const initialScope = (searchParams.get("scope") as KnowledgeScope | null) ?? "";
  const requestedProjectId = searchParams.get("project_id") ?? "";
  const [keywordInput, setKeywordInput] = useState(searchParams.get("keyword") ?? "");
  const [keyword, setKeyword] = useState(searchParams.get("keyword") ?? "");
  const [scope, setScope] = useState<KnowledgeScope | "">(initialScope);
  const [projectId, setProjectId] = useState(searchParams.get("project_id") ?? "");
  const [assetStatus, setAssetStatus] = useState<AssetStatus | "">(
    (searchParams.get("asset_status") as AssetStatus | null) ?? "",
  );
  const [confidentialityLevel, setConfidentialityLevel] = useState<ConfidentialityLevel | "">(
    (searchParams.get("confidentiality") as ConfidentialityLevel | null) ?? "",
  );
  const [includeArchived, setIncludeArchived] = useState(searchParams.get("archived") === "1");
  const [directory, setDirectory] = useState<KnowledgeDirectoryDTO | null>(null);
  const [directoryItems, setDirectoryItems] = useState<KnowledgeDirectoryDTO[]>([]);
  const [projectCatalog, setProjectCatalog] = useState<KnowledgeLibraryProjectDTO[]>([]);
  const [projectCatalogLoaded, setProjectCatalogLoaded] = useState(false);
  const [directoryLoading, setDirectoryLoading] = useState(false);
  const [directoryError, setDirectoryError] = useState(false);
  const [directoryRetryKey, setDirectoryRetryKey] = useState(0);
  const [mobileDirectoryOpen, setMobileDirectoryOpen] = useState(false);
  const [mobileFiltersOpen, setMobileFiltersOpen] = useState(false);
  const [page, setPage] = useState(Math.max(1, Number(searchParams.get("page")) || 1));
  const [result, setResult] = useState<KnowledgePageVM>(emptyPage);
  const [hasLoaded, setHasLoaded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryKey, setRetryKey] = useState(0);
  const requestRef = useRef(0);
  const directoryRequestRef = useRef(0);
  const restoredDirectoryRef = useRef(false);
  const restoredUrlContextRef = useRef("");
  const tableShellRef = useRef<HTMLDivElement>(null);
  const topScrollerRef = useRef<HTMLDivElement>(null);
  const [tableOverflow, setTableOverflow] = useState(false);
  const [tableScrollWidth, setTableScrollWidth] = useState(0);
  const [tableAtEnd, setTableAtEnd] = useState(false);

  const availableProjects = useMemo(() => {
    return projectCatalog.map((project) => ({
      projectId: project.project_id,
      projectName: project.name,
      accessLabel: project.access_label,
    }));
  }, [projectCatalog]);
  const validProjectId = availableProjects.some((project) => project.projectId === projectId)
    ? projectId
    : "";
  const canLoadBusinessKnowledge = status === "authenticated" && capabilities.isBusinessUser;
  const [summaryAssetId, setSummaryAssetId] = useState<string | null>(null);
  const summaryRequestRef = useRef(0);
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
  const [contentSearch, setContentSearch] = useState(searchParams.get("query_mode") === "content");
  const semanticRequestRef = useRef(0);
  const directoryKeyFromUrl = searchParams.get("directory_key");
  const visibleDirectoryItems = directoryItems.filter(
    (item) =>
      (!scope || item.scope === scope) &&
      !item.parent_key &&
      (scope !== "project" || !validProjectId || item.project_id === validProjectId),
  );
  const childDirectoryItems = directoryItems.filter(
    (item) =>
      Boolean(directory) &&
      item.parent_key === (directory?.parent_key ?? directory?.directory_key) &&
      item.project_id === directory?.project_id,
  );
  const showGlobalSearch = globalSearchMode || !scope;
  const selectedProject = availableProjects.find((item) => item.projectId === validProjectId);

  const selectScope = (nextScope: KnowledgeScope | "") => {
    setMobileDirectoryOpen(false);
    setScope(nextScope);
    setProjectId("");
    setDirectory(null);
    setGlobalSearchMode(!nextScope);
    setPage(1);
    navigate(nextScope ? `/knowledge?scope=${nextScope}` : "/knowledge?search=global");
  };
  const selectProject = (nextProjectId: string) => {
    setProjectId(nextProjectId);
    setDirectory(null);
    setPage(1);
    navigate(
      nextProjectId
        ? `/knowledge?scope=project&project_id=${encodeURIComponent(nextProjectId)}`
        : "/knowledge?scope=project",
    );
  };
  const selectDirectory = (item: KnowledgeDirectoryDTO) => {
    setMobileDirectoryOpen(false);
    setDirectory(item);
    setPage(1);
    const next = new URLSearchParams({ scope: item.scope, directory_key: item.directory_key });
    if (item.project_id) next.set("project_id", item.project_id);
    navigate(`/knowledge?${next}`);
  };

  const returnQuery = new URLSearchParams();
  if (scope) returnQuery.set("scope", scope);
  if (validProjectId) returnQuery.set("project_id", validProjectId);
  if (directory) returnQuery.set("directory_key", directory.directory_key);
  if (keyword) returnQuery.set("keyword", keyword);
  if (assetStatus) returnQuery.set("asset_status", assetStatus);
  if (confidentialityLevel) returnQuery.set("confidentiality", confidentialityLevel);
  if (includeArchived) returnQuery.set("archived", "1");
  if (page > 1) returnQuery.set("page", String(page));
  if (globalSearchMode) returnQuery.set("search", "global");
  if (contentSearch) returnQuery.set("query_mode", "content");
  const knowledgeReturnPath = `/knowledge${returnQuery.size ? `?${returnQuery}` : ""}`;
  const detailState = knowledgeDetailSource(
    knowledgeReturnPath,
    directory ? `返回${directory.name}` : "返回知识资产库",
    directory ? "directory" : "global-search",
  );

  const openDetail = (assetId: string) => {
    const requestId = ++summaryRequestRef.current;
    setSummaryAssetId(assetId);
    setSummaryDetail(null);
    setSummaryError(null);
    setRequestNote(null);
    setSummaryLoading(true);
    void fetchKnowledgeDetail(assetId)
      .then((detail) => {
        if (requestId === summaryRequestRef.current) setSummaryDetail(detail);
      })
      .catch(() => {
        if (requestId === summaryRequestRef.current)
          setSummaryError("详情暂时无法加载，请关闭后重试。");
      })
      .finally(() => {
        if (requestId === summaryRequestRef.current) setSummaryLoading(false);
      });
  };

  useEffect(
    () => () => {
      ++summaryRequestRef.current;
    },
    [],
  );

  const closeDetail = () => {
    if (requestBusy) return;
    ++summaryRequestRef.current;
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

  // A scope change invalidates in-flight results as well as the displayed result.
  const invalidateSemanticSearch = useCallback(() => {
    ++semanticRequestRef.current;
  }, []);
  useEffect(() => {
    invalidateSemanticSearch();
    setSemanticResult(null);
    setSemanticError(null);
    setSemanticBusy(false);
    return invalidateSemanticSearch;
  }, [
    scope,
    directory?.directory_key,
    directory?.project_id,
    globalSearchMode,
    includeArchived,
    invalidateSemanticSearch,
  ]);

  const runSemanticSearch = async () => {
    if (!semanticQuery.trim()) return;
    const requestId = ++semanticRequestRef.current;
    setSemanticBusy(true);
    setSemanticError(null);
    try {
      const response = await searchKnowledge({
        query: semanticQuery.trim(),
        scope: scope || "all",
        intent: "search",
        filters: {
          include_archived: includeArchived,
          directory_key: globalSearchMode ? undefined : directory?.directory_key,
          project_id: globalSearchMode ? undefined : directory?.project_id,
        },
      });
      if (requestId === semanticRequestRef.current) setSemanticResult(response);
    } catch {
      if (requestId === semanticRequestRef.current)
        setSemanticError("内容检索暂时无法完成，请重试。");
    } finally {
      if (requestId === semanticRequestRef.current) setSemanticBusy(false);
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
    const urlContext = searchParams.toString();
    if (restoredUrlContextRef.current === urlContext) return;
    restoredUrlContextRef.current = urlContext;
    const nextScope = (searchParams.get("scope") as KnowledgeScope | null) ?? "";
    const nextProjectId = searchParams.get("project_id") ?? "";
    const nextDirectoryKey = searchParams.get("directory_key");
    setScope(nextScope);
    setProjectId(nextProjectId);
    setGlobalSearchMode(searchParams.get("search") === "global");
    setContentSearch(searchParams.get("query_mode") === "content");
    setDirectory((currentDirectory) => {
      const matchesUrl =
        Boolean(nextDirectoryKey) &&
        currentDirectory?.directory_key === nextDirectoryKey &&
        (nextScope !== "project" || currentDirectory.project_id === nextProjectId);
      if (matchesUrl) return currentDirectory;
      restoredDirectoryRef.current = false;
      return null;
    });
  }, [searchParams]);

  useEffect(() => {
    if (!canLoadBusinessKnowledge) {
      setProjectCatalog([]);
      setProjectCatalogLoaded(true);
      return;
    }
    let active = true;
    setProjectCatalogLoaded(false);
    void fetchKnowledgeLibraryProjects()
      .then((items) => {
        if (active) setProjectCatalog(items);
      })
      .catch(() => {
        if (active) setProjectCatalog([]);
      })
      .finally(() => {
        if (active) setProjectCatalogLoaded(true);
      });
    return () => {
      active = false;
    };
  }, [canLoadBusinessKnowledge]);

  useEffect(() => {
    if (
      !projectCatalogLoaded ||
      scope !== "project" ||
      !projectId ||
      availableProjects.some((project) => project.projectId === projectId)
    ) {
      return;
    }
    setProjectId("");
    setDirectory(null);
    setPage(1);
    if (directoryKeyFromUrl) {
      setScope("");
      navigate("/knowledge", { replace: true });
    } else {
      navigate("/knowledge?scope=project", { replace: true });
    }
  }, [availableProjects, directoryKeyFromUrl, navigate, projectCatalogLoaded, projectId, scope]);

  useEffect(() => {
    if (!canLoadBusinessKnowledge) return;
    const directoryRequestId = ++directoryRequestRef.current;
    const requestedDirectoryScope = directoryKeyFromUrl?.split(".", 1)[0] ?? "";
    const mismatchedDirectoryScopeUrl =
      Boolean(directoryKeyFromUrl) && requestedDirectoryScope !== initialScope;
    const missingProjectDirectoryContext =
      initialScope === "project" && Boolean(directoryKeyFromUrl) && !requestedProjectId;
    if (mismatchedDirectoryScopeUrl || missingProjectDirectoryContext) {
      setDirectoryItems([]);
      setDirectory(null);
      setDirectoryLoading(false);
      setScope("");
      setProjectId("");
      restoredDirectoryRef.current = true;
      navigate("/knowledge", { replace: true });
      return;
    }
    let active = true;
    setDirectoryLoading(true);
    setDirectoryError(false);
    void fetchKnowledgeDirectories(scope ? { scope, projectId: projectId || undefined } : {})
      .then((items) => {
        if (!active || directoryRequestId !== directoryRequestRef.current) return;
        setDirectoryItems(items);
        if (directoryKeyFromUrl && !restoredDirectoryRef.current) {
          const restored = items.find(
            (item) =>
              item.directory_key === directoryKeyFromUrl &&
              item.scope === scope &&
              (scope !== "project" || item.project_id === projectId),
          );
          if (!restored) {
            ++directoryRequestRef.current;
            setDirectoryItems([]);
            setDirectory(null);
            setDirectoryLoading(false);
            setScope("");
            setProjectId("");
            restoredDirectoryRef.current = true;
            navigate("/knowledge", { replace: true });
            return;
          }
          setDirectory(restored);
          restoredDirectoryRef.current = true;
        }
      })
      .catch((cause: unknown) => {
        if (!active || directoryRequestId !== directoryRequestRef.current) return;
        setDirectoryItems([]);
        setDirectory(null);
        restoredDirectoryRef.current = false;
        setDirectoryError(true);
        if (
          directoryKeyFromUrl &&
          cause instanceof ApiError &&
          [401, 403, 404].includes(cause.status)
        ) {
          setScope("");
          setProjectId("");
          restoredDirectoryRef.current = true;
          navigate("/knowledge", { replace: true });
        }
      })
      .finally(() => {
        if (active && directoryRequestId === directoryRequestRef.current) {
          setDirectoryLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [
    canLoadBusinessKnowledge,
    directoryKeyFromUrl,
    directoryRetryKey,
    initialScope,
    navigate,
    projectId,
    requestedProjectId,
    scope,
  ]);

  const resetFilters = () => {
    setKeywordInput("");
    setKeyword("");
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
    keyword || assetStatus || confidentialityLevel || includeArchived || false,
  );
  const advancedFilterCount =
    Number(Boolean(assetStatus)) + Number(Boolean(confidentialityLevel)) + Number(includeArchived);

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
                  onClick={() => openDetail(asset.id)}
                >
                  {asset.title}
                </button>
              ) : (
                <button
                  className="kbl-title-link"
                  type="button"
                  title={asset.title}
                  aria-label={`快速查看《${asset.title}》`}
                  onClick={() => openDetail(asset.id)}
                >
                  {asset.title}
                </button>
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
            <span className="kbl-mobile-label">来源</span>
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
        key: "status",
        header: "状态",
        render: (asset) => (
          <>
            <span className="kbl-mobile-label">状态</span>
            <StatusBadge
              label={assetStatusLabel[asset.assetStatus] ?? asset.assetStatus}
              tone={statusTones[asset.assetStatus] ?? "neutral"}
            />
          </>
        ),
      },
      {
        key: "confidentiality",
        header: "保密等级",
        render: (asset) => (
          <>
            <span className="kbl-mobile-label">保密等级</span>
            <span className={`kbl-confidentiality is-${asset.confidentialityLevel}`}>
              {confidentialityLabels[asset.confidentialityLevel] ?? asset.confidentialityLevel}
            </span>
          </>
        ),
      },
      {
        key: "updated",
        header: "更新时间",
        className: "kbl-date-cell",
        render: (asset) => (
          <>
            <span className="kbl-mobile-label">更新时间</span>
            <time dateTime={asset.updatedAt}>{asset.updatedAt || "未提供"}</time>
          </>
        ),
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
              onClick={() => openDetail(asset.id)}
            >
              查看摘要
            </button>
          ) : asset.access.original ? (
            <Link
              className="product-button is-secondary is-small"
              to={`/knowledge/${encodeURIComponent(asset.id)}`}
              state={detailState}
            >
              打开详情
            </Link>
          ) : (
            <button
              className="product-button is-secondary is-small"
              type="button"
              onClick={() => openDetail(asset.id)}
            >
              查看摘要
            </button>
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
  }, [initialLoading, result.items, contentSearch]);

  return (
    <ProductPage className="kbl-page">
      <PageHeader
        title="知识资产库"
        description="浏览本项目知识与其他项目可共享摘要；跨项目原文仍需逐项申请。"
        actions={
          <ActionGroup label="知识库操作" className="knowledge-directory-create-actions">
            {scope === "company" && capabilities.isGovernance && (
              <CreateKnowledgeDirectoryButton
                scope="company"
                initialParent={directory?.parent_key ?? directory?.directory_key}
              />
            )}
            {scope === "project" &&
              validProjectId &&
              authMe?.projects.some(
                (project) =>
                  project.projectId === validProjectId && project.projectRole === "project_manager",
              ) && (
                <CreateKnowledgeDirectoryButton
                  scope="project"
                  projectId={validProjectId}
                  initialParent={directory?.parent_key ?? directory?.directory_key}
                />
              )}
            {can.viewUpload(capabilities) ? (
              <Link
                className="product-button is-primary"
                to={
                  validProjectId
                    ? `/upload?project_id=${encodeURIComponent(validProjectId)}`
                    : "/upload"
                }
              >
                <Upload size={16} aria-hidden="true" />
                上传资产
              </Link>
            ) : null}
          </ActionGroup>
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
          <div className="kbl-workspace">
            <aside className="kbl-navigation" aria-label="资料范围与目录">
              <nav className="kbl-library-nav" aria-label="资料范围">
                <button
                  type="button"
                  aria-current={showGlobalSearch ? "page" : undefined}
                  onClick={() => selectScope("")}
                >
                  <Search size={17} aria-hidden="true" /> 全库搜索
                </button>
                <button
                  type="button"
                  aria-current={scope === "company" ? "page" : undefined}
                  onClick={() => selectScope("company")}
                >
                  <Building2 size={17} aria-hidden="true" /> 公司库
                </button>
                {availableProjects.length > 0 && (
                  <button
                    type="button"
                    aria-current={scope === "project" ? "page" : undefined}
                    onClick={() => selectScope("project")}
                  >
                    <BriefcaseBusiness size={17} aria-hidden="true" /> 项目库
                  </button>
                )}
                <button
                  type="button"
                  aria-current={scope === "personal" ? "page" : undefined}
                  onClick={() => selectScope("personal")}
                >
                  <UserRound size={17} aria-hidden="true" /> 个人库
                </button>
              </nav>
              {scope && (
                <button
                  type="button"
                  className="kbl-mobile-directory-toggle"
                  aria-expanded={mobileDirectoryOpen}
                  aria-controls="knowledge-directory-navigation"
                  onClick={() => setMobileDirectoryOpen((value) => !value)}
                >
                  <Folder size={16} aria-hidden="true" />
                  <span>
                    {mobileDirectoryOpen
                      ? "收起目录"
                      : scope === "project"
                        ? "选择项目与目录"
                        : "选择目录"}
                  </span>
                  {directoryError && <small>加载失败，请重试</small>}
                  <ChevronRight size={16} aria-hidden="true" />
                </button>
              )}
              {scope ? (
                <div
                  id="knowledge-directory-navigation"
                  className={`kbl-directory-navigation${mobileDirectoryOpen ? " is-mobile-open" : ""}`}
                >
                  {scope === "project" && (
                    <label className="kbl-project-picker">
                      <span>当前项目</span>
                      <select
                        aria-label="项目"
                        value={validProjectId}
                        onChange={(event) => selectProject(event.target.value)}
                      >
                        <option value="">请选择项目</option>
                        {availableProjects.map((project) => (
                          <option key={project.projectId} value={project.projectId}>
                            {project.projectName} · {project.accessLabel}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                  <div className="kbl-directory-heading">
                    <h3>{scope === "project" && !validProjectId ? "可见项目" : "目录"}</h3>
                    {directory?.parent_key && (
                      <Link
                        to={`/knowledge?scope=${directory.scope}&directory_key=${encodeURIComponent(directory.parent_key)}${directory.project_id ? `&project_id=${encodeURIComponent(directory.project_id)}` : ""}`}
                      >
                        返回上级分类
                      </Link>
                    )}
                  </div>
                  {directoryLoading ? (
                    <p className="kbl-navigation-note" role="status">
                      正在读取可进入的目录…
                    </p>
                  ) : directoryError ? (
                    <div className="kbl-navigation-note" role="alert">
                      <p>目录暂时无法加载，请重试。</p>
                      <Button
                        size="small"
                        onClick={() => setDirectoryRetryKey((value) => value + 1)}
                      >
                        重新加载目录
                      </Button>
                    </div>
                  ) : scope === "project" && !validProjectId ? (
                    <div className="kbl-project-list">
                      {availableProjects.map((project) => (
                        <button
                          type="button"
                          key={project.projectId}
                          onClick={() => selectProject(project.projectId)}
                        >
                          <strong>{project.projectName}</strong>
                          <span>{project.accessLabel}</span>
                        </button>
                      ))}
                      {projectCatalogLoaded && availableProjects.length === 0 && (
                        <p className="kbl-navigation-note">暂无可进入的项目。</p>
                      )}
                    </div>
                  ) : (
                    <nav className="kbl-directory-tree" aria-label="知识目录">
                      {visibleDirectoryItems.map((item) => (
                        <div key={`${item.directory_key}-${item.project_id ?? "global"}`}>
                          <button
                            type="button"
                            aria-current={
                              directory?.directory_key === item.directory_key ? "page" : undefined
                            }
                            onClick={() => selectDirectory(item)}
                            title={item.display_path}
                          >
                            <Folder size={16} aria-hidden="true" />
                            <span>{item.name}</span>
                          </button>
                          {(directory?.directory_key === item.directory_key ||
                            directory?.parent_key === item.directory_key) &&
                            childDirectoryItems.length > 0 && (
                              <div className="kbl-child-directories">
                                {childDirectoryItems.map((child) => (
                                  <button
                                    type="button"
                                    key={child.directory_key}
                                    aria-current={
                                      directory?.directory_key === child.directory_key
                                        ? "page"
                                        : undefined
                                    }
                                    onClick={() => selectDirectory(child)}
                                    title={child.display_path}
                                  >
                                    <Folder size={15} aria-hidden="true" />
                                    <span>{child.name}</span>
                                  </button>
                                ))}
                              </div>
                            )}
                        </div>
                      ))}
                      {visibleDirectoryItems.length === 0 && (
                        <p className="kbl-navigation-note">当前范围暂无可进入的目录。</p>
                      )}
                    </nav>
                  )}
                </div>
              ) : (
                <p className="kbl-navigation-note">
                  选择资料库可按目录浏览。全库搜索只返回当前身份有权发现的资料。
                </p>
              )}
            </aside>
            <div className="kbl-results-workspace">
              <nav className="kbl-breadcrumbs" aria-label="知识资产目录路径">
                <button type="button" onClick={() => selectScope("")}>
                  知识资产库
                </button>
                <ChevronRight size={14} aria-hidden="true" />
                {scope ? (
                  <span>
                    {scope === "company" ? "公司库" : scope === "project" ? "项目库" : "个人库"}
                  </span>
                ) : (
                  <span aria-current="page">全库搜索</span>
                )}
                {selectedProject && (
                  <>
                    <ChevronRight size={14} aria-hidden="true" />
                    <span>{selectedProject.projectName}</span>
                  </>
                )}
                {directory && (
                  <>
                    <ChevronRight size={14} aria-hidden="true" />
                    <span aria-current="page">{directory.name}</span>
                  </>
                )}
              </nav>
              {scope && !directory && !globalSearchMode && (
                <EmptyState
                  title={
                    scope === "project" && !validProjectId ? "选择一个项目" : "选择目录查看资料"
                  }
                  description={
                    scope === "project" && !validProjectId
                      ? "选择可见项目，再进入资料目录；其他项目仍仅展示有权查看的内容。"
                      : "目录和资料列表会在同一工作区展示，选择后可按标题、正文或状态检索。"
                  }
                />
              )}
              {directory && (
                <div className="kbl-search-mode" role="group" aria-label="检索方式">
                  <button
                    type="button"
                    aria-pressed={!contentSearch}
                    onClick={() => setContentSearch(false)}
                  >
                    标题与标签
                  </button>
                  <button
                    type="button"
                    aria-pressed={contentSearch}
                    onClick={() => setContentSearch(true)}
                  >
                    正文与摘要
                  </button>
                </div>
              )}
              {((directory && contentSearch) || showGlobalSearch) && (
                <PageSection className="kbl-semantic-section">
                  <div className="kbl-semantic-heading">
                    <div>
                      <h2>{showGlobalSearch ? "全库搜索" : "正文与摘要检索"}</h2>
                      <p>
                        {showGlobalSearch
                          ? "搜索当前身份可见的正文与摘要；跨项目原文仍需逐项申请。"
                          : "仅检索当前目录内可访问的正文与摘要；内容检索使用目录范围和归档选项，不应用列表的其他筛选。"}
                      </p>
                    </div>
                  </div>
                  <form
                    onSubmit={(event) => {
                      event.preventDefault();
                      void runSemanticSearch();
                    }}
                    className="kbl-semantic-form"
                  >
                    <label htmlFor="semantic-query">正文关键词或内容描述</label>
                    <div>
                      <input
                        id="semantic-query"
                        value={semanticQuery}
                        onChange={(event) => setSemanticQuery(event.target.value)}
                        placeholder="输入正文编号、关键词或内容描述"
                      />
                      <Button
                        variant="primary"
                        type="submit"
                        disabled={semanticBusy || !semanticQuery.trim()}
                      >
                        {semanticBusy ? "检索中…" : "检索内容"}
                      </Button>
                    </div>
                    <label className="kbl-archive-toggle">
                      <input
                        type="checkbox"
                        checked={includeArchived}
                        onChange={(event) => setIncludeArchived(event.target.checked)}
                      />
                      <span>包含归档</span>
                    </label>
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
              {directory && !contentSearch && (
                <form className="kbl-filter-form" onSubmit={submitKeyword}>
                  <FilterBar ariaLabel="知识资产筛选">
                    <div className="kbl-filter-search-row">
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
                        className="product-button is-secondary is-small kbl-mobile-filter-toggle"
                        type="button"
                        aria-expanded={mobileFiltersOpen}
                        aria-controls="knowledge-advanced-filters"
                        onClick={() => setMobileFiltersOpen((value) => !value)}
                      >
                        筛选{advancedFilterCount ? ` (${advancedFilterCount})` : ""}
                      </button>
                    </div>
                    <div
                      id="knowledge-advanced-filters"
                      className={`kbl-advanced-filters${mobileFiltersOpen ? " is-mobile-open" : ""}`}
                    >
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
                            setConfidentialityLevel(
                              event.target.value as ConfidentialityLevel | "",
                            );
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
                      <button
                        className="product-button is-ghost is-small"
                        type="button"
                        disabled={!hasActiveFilters}
                        onClick={resetFilters}
                      >
                        重置
                      </button>
                    </div>
                  </FilterBar>
                </form>
              )}

              {requestNote && (
                <div className="kbl-request-feedback" role="status">
                  <span>{requestNote}</span>
                  <Link to="/original-access?box=mine">查看申请进度</Link>
                </div>
              )}

              {directory && !contentSearch && (
                <PageSection className="kbl-list-section">
                  <div className="kbl-scope-summary" aria-label="当前生效范围与筛选">
                    <strong>当前浏览范围</strong>
                    <span>{scope ? scopeLabels[scope] : "全部可见范围"}</span>
                    {validProjectId && (
                      <span>
                        {
                          availableProjects.find((item) => item.projectId === validProjectId)
                            ?.projectName
                        }
                      </span>
                    )}
                    {keyword && <span>关键词：{keyword}</span>}
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
                                  tableShellRef.current?.querySelector<HTMLElement>(
                                    ".kbl-table-wrap",
                                  );
                                if (tableWrap)
                                  tableWrap.scrollLeft = event.currentTarget.scrollLeft;
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
                              title={hasActiveFilters ? "当前条件没有匹配资料" : "暂无可复用资料"}
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
                        <PagePagination
                          className="kbl-pagination"
                          ariaLabel="知识资产分页"
                          page={result.page}
                          totalPages={totalPages}
                          hasNext={result.hasNext}
                          disabled={loading}
                          onPageChange={setPage}
                          summary={
                            <>
                              显示 {firstItem}-{lastItem} 条，共 {result.total} 条
                            </>
                          }
                        />
                      )}
                    </>
                  )}
                </PageSection>
              )}
            </div>
          </div>
        </>
      )}

      <DetailDrawer
        open={summaryAssetId !== null}
        title={summaryDetail?.title ?? "知识详情"}
        description={
          summaryDetail?.access.crossProjectSummary
            ? "其他项目 · 摘要可见。此处不授予项目空间权限，也不展示原文或项目治理信息。"
            : "查看资料摘要与核心信息，关闭后继续浏览当前列表。"
        }
        busy={requestBusy}
        onClose={closeDetail}
        footer={
          summaryDetail ? (
            summaryDetail.access.original ? (
              <Link
                className="product-button is-primary"
                to={`/knowledge/${summaryDetail.id}`}
                state={detailState}
              >
                {summaryDetail.access.crossProjectSummary
                  ? "原文访问已开放，查看详情"
                  : "打开完整详情"}
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
        {summaryDetail && (
          <KnowledgeMetadataEditor
            key={summaryDetail.id}
            asset={summaryDetail}
            onSaved={() => {
              closeDetail();
              setRetryKey((value) => value + 1);
            }}
          />
        )}
        {summaryLoading ? (
          <p role="status">正在加载安全摘要…</p>
        ) : summaryError ? (
          <div className="kbl-drawer-message is-error" role="alert">
            {summaryError}
          </div>
        ) : summaryDetail ? (
          <div className="kbl-summary-drawer">
            <div className="kbl-summary-drawer-meta">
              <span>
                {summaryDetail.scope === "project"
                  ? summaryDetail.projectName || "项目知识"
                  : summaryDetail.scope === "company"
                    ? "公司知识"
                    : "个人知识"}
              </span>
              <span>{confidentialityLabels[summaryDetail.confidentialityLevel]}</span>
            </div>
            {!summaryDetail.access.summary ? (
              <p>当前身份不可查看内容摘要。</p>
            ) : summaryDetail.detailed ||
              summaryDetail.oneLiner ||
              summaryDetail.keyPoints.length ? (
              <div>
                {(summaryDetail.detailed || summaryDetail.oneLiner) && (
                  <p>{summaryDetail.detailed || summaryDetail.oneLiner}</p>
                )}
                {summaryDetail.keyPoints.length > 0 && (
                  <ul>
                    {summaryDetail.keyPoints.map((point, index) => (
                      <li key={index}>{point}</li>
                    ))}
                  </ul>
                )}
              </div>
            ) : (
              <EmptyState
                title={summaryPendingLabel(summaryDetail)}
                description="摘要暂未就绪，不代表文件解析失败。原文访问仍按现有权限控制。"
              />
            )}
            <section className="kbl-summary-core" aria-labelledby="summary-core-title">
              <h3 id="summary-core-title">核心信息</h3>
              <dl>
                <div>
                  <dt>资料范围</dt>
                  <dd>
                    {summaryDetail.scope === "company"
                      ? "公司知识"
                      : summaryDetail.scope === "personal"
                        ? "个人知识"
                        : "项目知识"}
                  </dd>
                </div>
                {summaryDetail.scope === "project" && (
                  <div>
                    <dt>来源项目</dt>
                    <dd>{summaryDetail.projectName || "暂无"}</dd>
                  </div>
                )}
                <div>
                  <dt>正式目录</dt>
                  <dd>{summaryDetail.directoryPath || "待治理"}</dd>
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
