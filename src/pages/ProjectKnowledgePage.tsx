import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type KeyboardEvent,
} from "react";
import { Bot, ChevronLeft, ChevronRight, FileText, MoreHorizontal, Search } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  bulkDeleteKnowledgeAssets,
  deleteKnowledgeAsset,
  fetchKnowledgePage,
} from "../api/knowledge";
import { ControlledBulkRequestError } from "../api/bulk";
import { fetchProjectQaModelOptions, projectQa } from "../api/project";
import { preflightAssetization, registerAssetEvidence, submitAssetization } from "../api/review";
import { useAuth } from "../auth/AuthContext";
import DataTable, { type Column } from "../components/DataTable";
import ConfirmDialog from "../components/ConfirmDialog";
import WizardModal from "../components/WizardModal";
import { BulkSelectionRail, SelectionCheckbox } from "../components/BulkSelection";
import ProjectCompanyPublicationDialog, {
  getProjectCompanyPublicationEligibility,
} from "../components/ProjectCompanyPublicationDialog";
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
import type { AssetizationPreflightItemDTO, EvidenceInputDTO } from "../types/review";
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

function canSelectAsset(asset: KnowledgeCardVM, projectRole: string): boolean {
  return (
    asset.assetStatus !== "archived" &&
    ((asset.zone === "material" && asset.assetStatus === "active") ||
      (projectRole === "project_manager" && asset.access.canDelete))
  );
}

function canDeleteSelectedAsset(asset: KnowledgeCardVM, projectRole: string): boolean {
  return (
    projectRole === "project_manager" && asset.assetStatus !== "archived" && asset.access.canDelete
  );
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

  const [upgradeAsset, setUpgradeAsset] = useState<KnowledgeCardVM | null>(null);
  const [upgradeNotice, setUpgradeNotice] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);
  const [deleteBusyId, setDeleteBusyId] = useState<string | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleteNotice, setDeleteNotice] = useState<{
    tone: "success" | "error";
    text: string;
  } | null>(null);
  const [selectedAssets, setSelectedAssets] = useState<KnowledgeCardVM[]>([]);
  const [allMatchingSelected, setAllMatchingSelected] = useState(false);
  const [matchingSelectableAssets, setMatchingSelectableAssets] = useState<
    KnowledgeCardVM[] | null
  >(null);
  const [matchingSelectionLoading, setMatchingSelectionLoading] = useState(false);
  const [bulkDeleteOpen, setBulkDeleteOpen] = useState(false);
  const [bulkDeleteBusy, setBulkDeleteBusy] = useState(false);
  const [bulkAssetizeBusy, setBulkAssetizeBusy] = useState(false);
  const [assetizationOpen, setAssetizationOpen] = useState(false);
  const [assetizationStep, setAssetizationStep] = useState(0);
  const [assetizationItems, setAssetizationItems] = useState<AssetizationPreflightItemDTO[]>([]);
  const [assetizationError, setAssetizationError] = useState<string | null>(null);
  const [evidenceType, setEvidenceType] =
    useState<EvidenceInputDTO["evidence_type"]>("internal_sharing");
  const [evidenceCategory, setEvidenceCategory] =
    useState<EvidenceInputDTO["evidence_category"]>("meeting_minutes");
  const [evidenceDescription, setEvidenceDescription] = useState("");
  const bulkDeleteRunRef = useRef(false);
  const bulkRetrySelectionRef = useRef<KnowledgeCardVM[] | null>(null);

  useEffect(() => {
    const requestId = ++listRequestRef.current;
    const recoverySelection = bulkRetrySelectionRef.current;
    bulkRetrySelectionRef.current = null;
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
    setSelectedAssets([]);
    setAllMatchingSelected(false);
    setMatchingSelectableAssets(null);
    void fetchKnowledgePage(params)
      .then((nextResult) => {
        if (!active || requestId !== listRequestRef.current) return;
        setResult(nextResult);
        if (recoverySelection) setSelectedAssets(recoverySelection);
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

  const openUpgrade = useCallback(
    (asset: KnowledgeCardVM) => {
      const eligibility = getProjectCompanyPublicationEligibility(
        asset,
        project.projectId,
        project.projectRole,
      );
      if (!eligibility.eligible) return;
      setUpgradeAsset(asset);
      setUpgradeNotice(null);
    },
    [project.projectId, project.projectRole],
  );
  const handleDelete = useCallback(async (assetId: string) => {
    setDeleteBusyId(assetId);
    setDeleteNotice(null);
    try {
      await deleteKnowledgeAsset(assetId);
      setConfirmDeleteId(null);
      setDeleteNotice({ tone: "success", text: "已删除，资产移出项目知识库。" });
      setListRetryKey((value) => value + 1);
    } catch {
      setDeleteNotice({ tone: "error", text: "删除失败，请稍后重试。" });
    } finally {
      setDeleteBusyId(null);
    }
  }, []);

  const selectablePageAssets = result.items.filter((asset) =>
    canSelectAsset(asset, project.projectRole),
  );
  const selectedPageAssets = selectablePageAssets.filter((asset) =>
    selectedAssets.some((selected) => selected.id === asset.id),
  );
  const pageAllSelected =
    selectablePageAssets.length > 0 && selectedPageAssets.length === selectablePageAssets.length;
  const pageIndeterminate = selectedPageAssets.length > 0 && !pageAllSelected;

  const loadMatchingSelectableAssets = async () => {
    const request = listRequestRef.current;
    setMatchingSelectionLoading(true);
    try {
      const collected: KnowledgeCardVM[] = [];
      let nextPage = 1;
      let hasMore = true;
      while (hasMore) {
        const next = await fetchKnowledgePage({
          scope: "project",
          projectId: project.projectId,
          page: nextPage,
          pageSize: 100,
          keyword: keyword || undefined,
          zone: zone || undefined,
          assetType: assetType || undefined,
          assetStatus: assetStatus || undefined,
          confidentialityLevel: confidentialityLevel || undefined,
          updatedFrom: updatedFrom || undefined,
          updatedTo: updatedTo || undefined,
          sortBy,
          sortDirection,
          includeArchived,
        });
        collected.push(...next.items.filter((asset) => canSelectAsset(asset, project.projectRole)));
        hasMore = next.hasNext;
        nextPage += 1;
      }
      if (request !== listRequestRef.current) return null;
      setMatchingSelectableAssets(collected);
      return collected;
    } catch {
      setDeleteNotice({ tone: "error", text: "无法选择全部筛选结果，请刷新后重试。" });
      return null;
    } finally {
      if (request === listRequestRef.current) setMatchingSelectionLoading(false);
    }
  };

  const selectAllMatching = async () => {
    const collected = matchingSelectableAssets ?? (await loadMatchingSelectableAssets());
    if (!collected) {
      setSelectedAssets([]);
      setAllMatchingSelected(false);
      return;
    }
    setSelectedAssets(collected);
    setAllMatchingSelected(true);
  };

  const handleBulkDelete = async () => {
    const deletableAssets = selectedAssets.filter((asset) =>
      canDeleteSelectedAsset(asset, project.projectRole),
    );
    if (deletableAssets.length === 0 || bulkDeleteRunRef.current) return;
    const selectionSnapshot = [...deletableAssets];
    const selectionRequest = listRequestRef.current;
    bulkDeleteRunRef.current = true;
    setBulkDeleteBusy(true);
    try {
      const response = await bulkDeleteKnowledgeAssets({
        itemIds: selectionSnapshot.map((asset) => asset.id),
        scope: "project",
        projectId: project.projectId,
      });
      setBulkDeleteOpen(false);
      setSelectedAssets([]);
      setAllMatchingSelected(false);
      setDeleteNotice({
        tone: response.failed > 0 || response.skipped > 0 ? "error" : "success",
        text: `批量删除完成：提交 ${response.submitted}，成功 ${response.succeeded}，跳过 ${response.skipped}，失败 ${response.failed}。`,
      });
      setListRetryKey((value) => value + 1);
    } catch (error) {
      const retryIds =
        error instanceof ControlledBulkRequestError
          ? new Set(error.retryItems as string[])
          : new Set(selectionSnapshot.map((asset) => asset.id));
      const partial = error instanceof ControlledBulkRequestError ? error.partialResult : null;
      const selectionScopeUnchanged = listRequestRef.current === selectionRequest;
      setBulkDeleteOpen(false);
      if (selectionScopeUnchanged) {
        bulkRetrySelectionRef.current = selectionSnapshot.filter((asset) => retryIds.has(asset.id));
      }
      setAllMatchingSelected(false);
      setDeleteNotice({
        tone: "error",
        text: partial
          ? `批量删除中断：已完成提交 ${partial.submitted} 项（成功 ${partial.succeeded}，跳过 ${partial.skipped}，失败 ${partial.failed}），剩余 ${retryIds.size} 项可重试。`
          : `批量删除未开始，${retryIds.size} 项仍保留选择，可重试。`,
      });
      setListRetryKey((value) => value + 1);
    } finally {
      bulkDeleteRunRef.current = false;
      setBulkDeleteBusy(false);
    }
  };

  const openAssetization = async () => {
    const materialAssets = selectedAssets.filter(
      (asset) => asset.zone === "material" && asset.assetStatus === "active",
    );
    if (materialAssets.length === 0 || bulkAssetizeBusy) return;
    setAssetizationOpen(true);
    setAssetizationStep(0);
    setAssetizationError(null);
    setAssetizationItems([]);
    setBulkAssetizeBusy(true);
    try {
      setAssetizationItems(
        await preflightAssetization(
          project.projectId,
          materialAssets.map((asset) => asset.id),
        ),
      );
    } catch {
      setAssetizationError("证据预检暂时未完成，请稍后重试。未创建任何审核任务。");
    } finally {
      setBulkAssetizeBusy(false);
    }
  };

  const completeAssetization = async () => {
    const missing = assetizationItems.filter((item) => item.status === "evidence_missing");
    const eligible = assetizationItems.filter((item) => item.status !== "ineligible");
    if (!evidenceDescription.trim() && missing.length > 0) {
      setAssetizationError("请填写证据适用说明，说明为何可用于这些资料。");
      return;
    }
    setBulkAssetizeBusy(true);
    setAssetizationError(null);
    try {
      const evidence: EvidenceInputDTO = {
        evidence_type: evidenceType,
        evidence_category: evidenceCategory,
        description: evidenceDescription.trim(),
        idempotency_key: crypto.randomUUID(),
      };
      for (const item of missing) {
        await registerAssetEvidence(project.projectId, item.item_id, evidence);
      }
      const response = await submitAssetization(
        project.projectId,
        eligible.map((item) => item.item_id),
      );
      setAssetizationOpen(false);
      setSelectedAssets([]);
      setAllMatchingSelected(false);
      setUpgradeNotice({
        tone:
          response.failed || response.evidence_missing || response.ineligible ? "error" : "success",
        text: `资产化审核已提交：新建 ${response.created}，复用待办 ${response.existing}，缺证据 ${response.evidence_missing}，不可发起 ${response.ineligible}，失败 ${response.failed}。`,
      });
      setListRetryKey((value) => value + 1);
    } catch {
      setAssetizationError("提交未全部完成。已成功登记的证据会保留，可再次预检后重试。");
    } finally {
      setBulkAssetizeBusy(false);
    }
  };

  const selectedMaterialAssets = selectedAssets.filter(
    (asset) => asset.zone === "material" && asset.assetStatus === "active",
  );
  const selectedDeletableAssets = selectedAssets.filter((asset) =>
    canDeleteSelectedAsset(asset, project.projectRole),
  );

  const columns: Column<KnowledgeCardVM>[] = [
    {
      key: "select",
      header:
        selectablePageAssets.length > 0 ? (
          <SelectionCheckbox
            checked={pageAllSelected}
            indeterminate={pageIndeterminate}
            disabled={selectablePageAssets.length === 0 || bulkDeleteBusy || bulkAssetizeBusy}
            label="全选当前页项目知识"
            onChange={() => {
              if (pageAllSelected) {
                const pageIds = new Set(selectablePageAssets.map((asset) => asset.id));
                setSelectedAssets((current) => current.filter((asset) => !pageIds.has(asset.id)));
                setAllMatchingSelected(false);
              } else {
                setSelectedAssets((current) => [
                  ...current.filter(
                    (asset) => !selectablePageAssets.some((pageAsset) => pageAsset.id === asset.id),
                  ),
                  ...selectablePageAssets,
                ]);
                if (matchingSelectableAssets === null) {
                  void loadMatchingSelectableAssets();
                }
              }
            }}
          />
        ) : null,
      render: (asset) =>
        canSelectAsset(asset, project.projectRole) ? (
          <SelectionCheckbox
            checked={selectedAssets.some((selected) => selected.id === asset.id)}
            disabled={bulkDeleteBusy || bulkAssetizeBusy}
            label={`选择项目知识 ${asset.title}`}
            onChange={() => {
              setAllMatchingSelected(false);
              if (matchingSelectableAssets === null) {
                void loadMatchingSelectableAssets();
              }
              setSelectedAssets((current) =>
                current.some((selected) => selected.id === asset.id)
                  ? current.filter((selected) => selected.id !== asset.id)
                  : [...current, asset],
              );
            }}
          />
        ) : null,
    },
    {
      key: "title",
      header: "知识名称",
      className: "pk-title-cell",
      render: (asset) => (
        <Link
          className="pk-title"
          to={`/knowledge/${asset.id}`}
          state={{
            backTo: `/project/${project.projectId}/knowledge`,
            backLabel: "返回项目知识库",
            source: "project",
          }}
        >
          <FileText size={17} aria-hidden="true" />
          <strong title={asset.title}>{asset.title}</strong>
        </Link>
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
      render: (asset) => {
        const publication = getProjectCompanyPublicationEligibility(
          asset,
          project.projectId,
          project.projectRole,
        );
        const canDelete =
          project.projectRole === "project_manager" &&
          asset.zone === "asset" &&
          asset.access.canDelete &&
          asset.assetStatus !== "archived";
        return (
          <div className="pk-row-actions">
            {publication.eligible ? (
              <button
                className="pk-publish-action"
                type="button"
                onClick={() => openUpgrade(asset)}
              >
                发布到公司知识库
              </button>
            ) : (
              <span className="pk-publication-reason">{publication.reason}</span>
            )}
            {canDelete && (
              <details className="pk-more-actions">
                <summary aria-label={`更多操作：${asset.title}`} title="更多操作">
                  <MoreHorizontal size={16} aria-hidden="true" />
                </summary>
                <div className="pk-more-actions-menu" role="menu">
                  <button
                    type="button"
                    className="is-danger"
                    role="menuitem"
                    disabled={deleteBusyId === asset.id}
                    onClick={() => setConfirmDeleteId(asset.id)}
                  >
                    {deleteBusyId === asset.id ? "删除中…" : "删除"}
                  </button>
                </div>
              </details>
            )}
          </div>
        );
      },
    },
  ];

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
          <div className="pk-header-actions">
            <Link
              className="product-button is-secondary is-small"
              to={`/project/${project.projectId}`}
            >
              返回项目空间
            </Link>
            <label className="pk-project-switcher" htmlFor="pk-project-switcher-header">
              <span>切换项目</span>
              <select
                id="pk-project-switcher-header"
                value={project.projectId}
                onChange={(event) => onSwitch(event.target.value)}
              >
                {projects.map((item) => (
                  <option key={item.projectId} value={item.projectId}>
                    {item.projectName}
                  </option>
                ))}
              </select>
            </label>
          </div>
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
          <label className="pk-select-field" htmlFor="pk-filter-zone">
            <span className="sr-only">资料区域</span>
            <select
              id="pk-filter-zone"
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
          <label className="pk-select-field" htmlFor="pk-filter-type">
            <span className="sr-only">资产类型</span>
            <select
              id="pk-filter-type"
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
          <label className="pk-select-field" htmlFor="pk-filter-status">
            <span className="sr-only">资产状态</span>
            <select
              id="pk-filter-status"
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
          <label className="pk-select-field" htmlFor="pk-filter-confidentiality">
            <span className="sr-only">保密级别</span>
            <select
              id="pk-filter-confidentiality"
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
              <label htmlFor="pk-filter-updated-from">
                <span>更新开始</span>
                <input
                  id="pk-filter-updated-from"
                  type="date"
                  value={updatedFrom}
                  onChange={(event) => {
                    setUpdatedFrom(event.target.value);
                    setPage(1);
                  }}
                />
              </label>
              <label htmlFor="pk-filter-updated-to">
                <span>更新结束</span>
                <input
                  id="pk-filter-updated-to"
                  type="date"
                  value={updatedTo}
                  onChange={(event) => {
                    setUpdatedTo(event.target.value);
                    setPage(1);
                  }}
                />
              </label>
              <label htmlFor="pk-filter-sort-by">
                <span>排序字段</span>
                <select
                  id="pk-filter-sort-by"
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
              <label htmlFor="pk-filter-sort-direction">
                <span>排序方向</span>
                <select
                  id="pk-filter-sort-direction"
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
              <label className="pk-archive-toggle" htmlFor="pk-filter-include-archived">
                <input
                  id="pk-filter-include-archived"
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
            {deleteNotice && (
              <div className={`pk-delete-notice is-${deleteNotice.tone}`} role="status">
                {deleteNotice.text}
              </div>
            )}
            <BulkSelectionRail
              selectedCount={selectedAssets.length}
              pageSelectedCount={selectedPageAssets.length}
              matchingCount={matchingSelectableAssets?.length ?? selectedPageAssets.length}
              allMatchingSelected={allMatchingSelected}
              matchingPending={matchingSelectionLoading}
              busy={bulkDeleteBusy || bulkAssetizeBusy}
              onSelectAllMatching={
                matchingSelectableAssets &&
                matchingSelectableAssets.length > selectedPageAssets.length
                  ? () => void selectAllMatching()
                  : undefined
              }
              onClear={() => {
                setSelectedAssets([]);
                setAllMatchingSelected(false);
              }}
            >
              {selectedMaterialAssets.length > 0 && (
                <button
                  className="product-button is-small"
                  disabled={bulkAssetizeBusy || bulkDeleteBusy}
                  onClick={() => void openAssetization()}
                  type="button"
                >
                  发起资产化审核（{selectedMaterialAssets.length}）
                </button>
              )}
              {selectedDeletableAssets.length > 0 && (
                <button
                  className="product-button is-danger is-small"
                  disabled={bulkDeleteBusy || bulkAssetizeBusy}
                  onClick={() => setBulkDeleteOpen(true)}
                  type="button"
                >
                  批量删除（{selectedDeletableAssets.length}）
                </button>
              )}
            </BulkSelectionRail>
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
            {confirmDeleteId && (
              <div
                className="pk-delete-overlay"
                role="dialog"
                aria-modal="true"
                aria-label="删除确认"
              >
                <div className="pk-delete-confirm">
                  <p>
                    确定要删除{" "}
                    <strong>
                      "{result.items.find((item) => item.id === confirmDeleteId)?.title ?? "该资产"}
                      "
                    </strong>{" "}
                    吗？
                  </p>
                  <p className="pk-delete-hint">删除后将无法恢复，关联的知识引用也会失效。</p>
                  <div className="pk-delete-actions">
                    <button
                      className="product-button is-secondary is-small"
                      type="button"
                      disabled={deleteBusyId === confirmDeleteId}
                      onClick={() => setConfirmDeleteId(null)}
                    >
                      取消
                    </button>
                    <button
                      className="product-button is-danger is-small"
                      type="button"
                      disabled={deleteBusyId === confirmDeleteId}
                      onClick={() => void handleDelete(confirmDeleteId)}
                    >
                      {deleteBusyId === confirmDeleteId ? "删除中…" : "确认删除"}
                    </button>
                  </div>
                </div>
              </div>
            )}
            <ConfirmDialog
              open={bulkDeleteOpen}
              title={`批量删除 ${selectedDeletableAssets.length} 项项目知识`}
              description={`目标项目：${project.projectName}。删除后资料将退出列表、检索、问答与原文授权；服务端会逐项重新核验项目归属、成员权限、状态及引用/保留约束，变化项会安全跳过。`}
              confirmText="确认批量删除"
              danger
              busy={bulkDeleteBusy}
              onCancel={() => {
                if (!bulkDeleteBusy) setBulkDeleteOpen(false);
              }}
              onConfirm={() => void handleBulkDelete()}
            />
            <ProjectCompanyPublicationDialog
              projectId={project.projectId}
              target={upgradeAsset}
              onClose={() => setUpgradeAsset(null)}
              onSubmitted={() => {
                setUpgradeAsset(null);
                setUpgradeNotice({ tone: "success", text: "已提交公司发布申请。" });
              }}
            />
            <WizardModal
              open={assetizationOpen}
              title="发起资产化审核"
              description="资料区转为资产区需要验证证据。证据只是支持内部分享或客户验证的治理线索，不代表平台已核验业务事实。"
              steps={[
                { label: "核对资料", description: "查看证据与资格" },
                { label: "补充证据", description: "仅为缺失项登记" },
                { label: "提交审核", description: "等待项目经理处理" },
              ]}
              currentStep={assetizationStep}
              busy={bulkAssetizeBusy}
              nextDisabled={
                assetizationItems.length === 0 ||
                (assetizationStep === 1 &&
                  assetizationItems.some((item) => item.status === "evidence_missing") &&
                  !evidenceDescription.trim())
              }
              completeDisabled={assetizationItems.every((item) => item.status === "ineligible")}
              completeText="提交资产化审核"
              onBack={() => setAssetizationStep((value) => Math.max(0, value - 1))}
              onNext={() => setAssetizationStep((value) => Math.min(2, value + 1))}
              onCancel={() => {
                if (!bulkAssetizeBusy) setAssetizationOpen(false);
              }}
              onComplete={() => void completeAssetization()}
            >
              {assetizationError && (
                <p className="pk-assetization-error" role="alert">
                  {assetizationError}
                </p>
              )}
              {assetizationStep === 0 && (
                <div className="pk-assetization-review">
                  <div className="pk-assetization-counts">
                    <strong>
                      {assetizationItems.filter((item) => item.status === "ready").length}
                    </strong>
                    <span>已有证据</span>
                    <strong>
                      {
                        assetizationItems.filter((item) => item.status === "evidence_missing")
                          .length
                      }
                    </strong>
                    <span>缺少证据</span>
                    <strong>
                      {assetizationItems.filter((item) => item.status === "ineligible").length}
                    </strong>
                    <span>不可发起</span>
                  </div>
                  <ul>
                    {assetizationItems.map((item) => (
                      <li key={item.item_id}>
                        <strong>{item.title}</strong>
                        <span>{item.message}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {assetizationStep === 1 && (
                <div className="pk-assetization-form">
                  <p>以下登记仅绑定到本次选择中缺少证据的资料；已有证据项不会重复创建。</p>
                  <label>
                    <span>证据类型</span>
                    <select
                      value={evidenceType}
                      onChange={(event) =>
                        setEvidenceType(event.target.value as EvidenceInputDTO["evidence_type"])
                      }
                    >
                      <option value="internal_sharing">内部分享</option>
                      <option value="client_validation">客户验证</option>
                    </select>
                  </label>
                  <label>
                    <span>证据类别</span>
                    <select
                      value={evidenceCategory}
                      onChange={(event) =>
                        setEvidenceCategory(
                          event.target.value as EvidenceInputDTO["evidence_category"],
                        )
                      }
                    >
                      <option value="meeting_minutes">会议纪要</option>
                      <option value="wecom_record">企业沟通记录</option>
                      <option value="client_email">客户邮件</option>
                      <option value="acceptance_doc">验收文件</option>
                      <option value="delivery_adoption">交付采纳记录</option>
                    </select>
                  </label>
                  <label>
                    <span>适用说明</span>
                    <textarea
                      value={evidenceDescription}
                      onChange={(event) => setEvidenceDescription(event.target.value)}
                      placeholder="说明适用项目、场景和资料范围"
                    />
                  </label>
                </div>
              )}
              {assetizationStep === 2 && (
                <div className="pk-assetization-summary">
                  <strong>提交后状态是“待审核”，不是已完成资产化。</strong>
                  <p>服务端会逐项复核项目归属、资料状态和证据。已有待办会复用，不会重复建单。</p>
                </div>
              )}
            </WizardModal>
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
                    <label htmlFor="pk-qa-model">
                      <span>问答模型</span>
                      <select
                        id="pk-qa-model"
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
      <label className="pk-project-switcher" htmlFor="pk-project-switcher">
        <span>切换项目</span>
        <select
          id="pk-project-switcher"
          value=""
          onChange={(event) => navigate(`/project/${event.target.value}/knowledge`)}
        >
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
