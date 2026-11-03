import { FileText } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError } from "../../../api/http";
import {
  fetchKnowledgeDetail,
  fetchKnowledgeDirectories,
  fetchKnowledgeLibraryProjects,
  fetchKnowledgePage,
  requestOriginalAccess,
  searchKnowledge,
} from "../../../api/knowledge";
import { useAuth } from "../../../auth/AuthContext";
import { accessLabel } from "../../../components/AccessExplanationDrawer";
import { type Column } from "../../../components/DataTable";
import StatusBadge from "../../../components/StatusBadge";
import { knowledgeDetailSource } from "../../../routing/knowledgeDetailSource";
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
} from "../../../types/knowledge";
import type { SearchResponseDTO } from "../../../types/search";
import { assetStatusLabel, scopeLabels } from "../../../utils/knowledgeLabels";
import { confidentialityLabels, emptyPage, PAGE_SIZE, statusTones } from "./model";

export function useKnowledgeList() {
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
  const [projectCatalogError, setProjectCatalogError] = useState(false);
  const [projectCatalogRetry, setProjectCatalogRetry] = useState(0);
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
  const directoryAncestors: KnowledgeDirectoryDTO[] = [];
  let ancestorKey = directory?.parent_key;
  const ancestorKeys = new Set<string>();
  while (ancestorKey && !ancestorKeys.has(ancestorKey)) {
    ancestorKeys.add(ancestorKey);
    const ancestor = directoryItems.find(
      (item) =>
        item.directory_key === ancestorKey &&
        item.scope === directory?.scope &&
        item.project_id === directory?.project_id,
    );
    if (!ancestor) break;
    directoryAncestors.unshift(ancestor);
    ancestorKey = ancestor.parent_key;
  }

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
    setProjectCatalogError(false);
    void fetchKnowledgeLibraryProjects()
      .then((items) => {
        if (active) setProjectCatalog(items);
      })
      .catch(() => {
        if (active) {
          setProjectCatalog([]);
          setProjectCatalogError(true);
        }
      })
      .finally(() => {
        if (active) setProjectCatalogLoaded(true);
      });
    return () => {
      active = false;
    };
  }, [canLoadBusinessKnowledge, projectCatalogRetry]);

  useEffect(() => {
    if (
      !projectCatalogLoaded ||
      projectCatalogError ||
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
  }, [
    availableProjects,
    directoryKeyFromUrl,
    navigate,
    projectCatalogLoaded,
    projectCatalogError,
    projectId,
    scope,
  ]);

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
            <span className="workspace-file-mark" aria-hidden="true">
              <FileText size={20} />
            </span>
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
              ) : asset.access.summary ? (
                <p className="kbl-summary-muted">摘要暂未就绪</p>
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
  return {
    status,
    capabilities,
    showGlobalSearch,
    selectScope,
    scope,
    mobileDirectoryOpen,
    setMobileDirectoryOpen,
    directoryError,
    projectCatalogError,
    validProjectId,
    selectProject,
    availableProjects,
    directory,
    setProjectCatalogRetry,
    projectCatalogLoaded,
    directoryLoading,
    setDirectoryRetryKey,
    visibleDirectoryItems,
    selectDirectory,
    childDirectoryItems,
    authMe,
    selectedProject,
    directoryAncestors,
    contentSearch,
    hasLoaded,
    loading,
    error,
    result,
    globalSearchMode,
    setContentSearch,
    runSemanticSearch,
    semanticQuery,
    setSemanticQuery,
    semanticBusy,
    includeArchived,
    setIncludeArchived,
    semanticError,
    semanticResult,
    detailState,
    submitKeyword,
    keywordInput,
    setKeywordInput,
    keyword,
    clearKeyword,
    mobileFiltersOpen,
    setMobileFiltersOpen,
    advancedFilterCount,
    assetStatus,
    setAssetStatus,
    setPage,
    confidentialityLevel,
    setConfidentialityLevel,
    hasActiveFilters,
    resetFilters,
    requestNote,
    setRetryKey,
    tableOverflow,
    tableAtEnd,
    tableShellRef,
    topScrollerRef,
    tableScrollWidth,
    columns,
    initialLoading,
    totalPages,
    firstItem,
    lastItem,
    summaryAssetId,
    summaryDetail,
    requestBusy,
    closeDetail,
    setRequestAsset,
    setRequestReason,
    summaryLoading,
    summaryError,
    setExplainAsset,
    explainAsset,
    setRequestError,
    requestAsset,
    submitOriginalRequest,
    requestReason,
    requestError,
  };
}
export type KnowledgeListController = ReturnType<typeof useKnowledgeList>;
