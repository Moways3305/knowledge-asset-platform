import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { fetchAuthMe, type AuthMeVM } from "../../../api/auth";
import { ControlledBulkRequestError } from "../../../api/bulk";
import { ApiError } from "../../../api/http";
import { bulkDeleteKnowledgeAssets } from "../../../api/knowledge";
import {
  createMyKnowledgeBase,
  fetchMyKnowledge,
  fetchMyKnowledgeBase,
  renameMyKnowledgeBase,
  type PersonalKbDTO,
} from "../../../api/personal";
import {
  createPublicationNamingValue,
  type PublicationNamingValue,
} from "../../../components/PublicationNamingFields";
import { useModelSelection } from "../../../hooks/useModelSelection";
import type { PersonalKnowledgeItemVM, PersonalKnowledgeState } from "../../../types/myKnowledge";
import type { NamingPreviewDTO } from "../../../types/naming";
import {
  DialogKind,
  EvidenceType,
  LoadState,
  PAGE_SIZE,
  emptySummary,
  evidenceCategories,
  isProjectLocked,
  safeActionError,
} from "./model";

export function useMyKnowledge() {
  const [items, setItems] = useState<PersonalKnowledgeItemVM[]>([]);
  const [summary, setSummary] = useState(emptySummary);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [hasNext, setHasNext] = useState(false);
  const [searchInput, setSearchInput] = useState("");
  const [keyword, setKeyword] = useState("");
  const [assetType, setAssetType] = useState("");
  const [personalState, setPersonalState] = useState<PersonalKnowledgeState | "">("");
  const [sortBy, setSortBy] = useState<"updated_at" | "created_at" | "title">("updated_at");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("desc");
  const [filterOpen, setFilterOpen] = useState(false);
  const [menuId, setMenuId] = useState<string | null>(null);
  const [projects, setProjects] = useState<AuthMeVM["projects"]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [kbState, setKbState] = useState<LoadState>("loading");
  const [kb, setKb] = useState<PersonalKbDTO | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [dialogKind, setDialogKind] = useState<DialogKind>(null);
  const [activeItem, setActiveItem] = useState<PersonalKnowledgeItemVM | null>(null);
  const [actionBusy, setActionBusy] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [kbName, setKbName] = useState("");
  const [targetProject, setTargetProject] = useState("");
  const [publicationNaming, setPublicationNaming] = useState<PublicationNamingValue>(() =>
    createPublicationNamingValue(""),
  );
  const [publicationPreview, setPublicationPreview] = useState<NamingPreviewDTO | null>(null);
  const [evidenceType, setEvidenceType] = useState<EvidenceType>("internal_sharing");
  const [evidenceCategory, setEvidenceCategory] = useState(evidenceCategories[0]);
  const [evidenceDescription, setEvidenceDescription] = useState("");
  const [editTitle, setEditTitle] = useState("");
  const [editType, setEditType] = useState("");
  const [editTags, setEditTags] = useState("");
  const [deleteReason, setDeleteReason] = useState("");
  const [selectedItems, setSelectedItems] = useState<PersonalKnowledgeItemVM[]>([]);
  const [allMatchingSelected, setAllMatchingSelected] = useState(false);
  const [matchingSelectableItems, setMatchingSelectableItems] = useState<
    PersonalKnowledgeItemVM[] | null
  >(null);
  const [matchingSelectionLoading, setMatchingSelectionLoading] = useState(false);
  const requestRef = useRef(0);
  const bulkRunRef = useRef(false);
  const models = useModelSelection();

  const load = useCallback(async () => {
    const request = ++requestRef.current;
    setLoadState("loading");
    setSelectedItems([]);
    setAllMatchingSelected(false);
    setMatchingSelectableItems(null);
    try {
      const result = await fetchMyKnowledge({
        page,
        pageSize: PAGE_SIZE,
        keyword: keyword || undefined,
        assetType: assetType || undefined,
        personalState: personalState || undefined,
        sortBy,
        sortDirection,
      });
      if (request !== requestRef.current) return;
      setItems(result.items);
      setSummary(result.summary);
      setTotal(result.total);
      setHasNext(result.hasNext);
      setLoadState("ready");
    } catch (error) {
      if (request !== requestRef.current) return;
      setItems([]);
      setTotal(0);
      setHasNext(false);
      setLoadState(error instanceof ApiError && error.status === 403 ? "forbidden" : "error");
    }
  }, [assetType, keyword, page, personalState, sortBy, sortDirection]);

  const loadKb = useCallback(async () => {
    try {
      setKb(await fetchMyKnowledgeBase());
      setKbState("ready");
    } catch (error) {
      setKb(null);
      setKbState(error instanceof ApiError && error.status === 403 ? "forbidden" : "error");
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      requestRef.current += 1;
    };
  }, [load]);

  useEffect(() => {
    void loadKb();
    void fetchAuthMe()
      .then((me) => setProjects(me.projects))
      .catch((error: unknown) => {
        console.error("Failed to load current user projects:", error);
        setProjects([]);
      });
  }, [loadKb]);

  useEffect(() => {
    const close = () => {
      setFilterOpen(false);
      setMenuId(null);
    };
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    document.addEventListener("click", close);
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("click", close);
      document.removeEventListener("keydown", keydown);
    };
  }, []);

  const openItemDialog = (kind: DialogKind, item: PersonalKnowledgeItemVM) => {
    setActiveItem(item);
    setDialogKind(kind);
    setTargetProject("");
    setPublicationNaming(createPublicationNamingValue(item.title));
    setPublicationPreview(null);
    setEvidenceType("internal_sharing");
    setEvidenceCategory(evidenceCategories[0]);
    setEvidenceDescription("");
    setEditTitle(item.title);
    setEditType(item.assetType);
    setEditTags(item.tags.join("，"));
    setDeleteReason("");
    setActionError(null);
    setMenuId(null);
  };

  const closeDialog = () => {
    if (actionBusy) return;
    setDialogKind(null);
    setActiveItem(null);
    setActionError(null);
  };

  const refreshAfterAction = async (message: string) => {
    setDialogKind(null);
    setActiveItem(null);
    setNotice(message);
    await load();
  };

  const runItemAction = async (
    action: () => Promise<unknown>,
    message: string,
    fallback: string,
  ) => {
    setActionBusy(true);
    setActionError(null);
    try {
      await action();
      await refreshAfterAction(message);
    } catch (error) {
      setActionError(safeActionError(error, fallback));
    } finally {
      setActionBusy(false);
    }
  };

  const createKb = async (includeModels: boolean) => {
    if (includeModels && models.blockSubmit) {
      setActionError("默认模型尚未配置，请联系管理员完成配置");
      return;
    }
    setActionBusy(true);
    setActionError(null);
    setNotice(null);
    try {
      const data = await createMyKnowledgeBase({
        displayName: kbName.trim() || undefined,
        embeddingModelRef: includeModels ? models.embeddingRef || undefined : undefined,
        rerankModelRef: includeModels ? models.rerankRef || undefined : undefined,
      });
      setKb(data);
      setKbState("ready");
      setDialogKind(null);
      if (data.status === "init_failed") {
        setActionError("个人知识库初始化失败，请重试初始化或联系管理员。");
      } else if (data.status === "active") {
        setNotice(includeModels ? "个人知识库已就绪" : "个人知识库初始化已完成");
      } else {
        setNotice("请求已受理，知识库尚未就绪，请稍后刷新状态。");
      }
    } catch (error) {
      setActionError(safeActionError(error, "创建失败，请稍后重试"));
    } finally {
      setActionBusy(false);
    }
  };

  const renameKb = async () => {
    if (!kbName.trim()) {
      setActionError("请输入知识库名称");
      return;
    }
    setActionBusy(true);
    setActionError(null);
    try {
      const data = await renameMyKnowledgeBase(kbName.trim());
      setKb(data);
      setDialogKind(null);
      setNotice(data.weknora_sync_failed ? "名称已保存，检索服务同步稍后重试" : "知识库名称已更新");
    } catch (error) {
      setActionError(safeActionError(error, "改名失败，请稍后重试"));
    } finally {
      setActionBusy(false);
    }
  };

  const submitSearch = (event: FormEvent) => {
    event.preventDefault();
    setPage(1);
    setKeyword(searchInput.trim());
  };

  const clearFilters = () => {
    setAssetType("");
    setPersonalState("");
    setSortBy("updated_at");
    setSortDirection("desc");
    setPage(1);
  };

  const canBulkDelete = (item: PersonalKnowledgeItemVM) =>
    item.access.canDelete && !isProjectLocked(item);
  const isBulkSelectable = canBulkDelete;
  const selectablePageItems = items.filter(isBulkSelectable);
  const selectedPageItems = selectablePageItems.filter((item) =>
    selectedItems.some((selected) => selected.id === item.id),
  );
  const pageAllSelected =
    selectablePageItems.length > 0 && selectedPageItems.length === selectablePageItems.length;
  const pageIndeterminate = selectedPageItems.length > 0 && !pageAllSelected;
  const selectedDeleteItems = selectedItems.filter(canBulkDelete);

  const loadMatchingSelectableItems = async () => {
    const request = requestRef.current;
    setMatchingSelectionLoading(true);
    try {
      const collected: PersonalKnowledgeItemVM[] = [];
      let nextPage = 1;
      let hasMore = true;
      while (hasMore) {
        const result = await fetchMyKnowledge({
          page: nextPage,
          pageSize: 100,
          keyword: keyword || undefined,
          assetType: assetType || undefined,
          personalState: personalState || undefined,
          sortBy,
          sortDirection,
        });
        collected.push(...result.items.filter(isBulkSelectable));
        hasMore = result.hasNext;
        nextPage += 1;
      }
      if (request !== requestRef.current) return null;
      setMatchingSelectableItems(collected);
      return collected;
    } catch {
      setNotice("无法选择全部筛选结果，请刷新后重试");
      return null;
    } finally {
      if (request === requestRef.current) setMatchingSelectionLoading(false);
    }
  };

  const selectAllMatching = async () => {
    const collected = matchingSelectableItems ?? (await loadMatchingSelectableItems());
    if (!collected) {
      setSelectedItems([]);
      setAllMatchingSelected(false);
      return;
    }
    setSelectedItems(collected);
    setAllMatchingSelected(true);
  };

  const runPersonalBulkDelete = async () => {
    const targets = selectedDeleteItems;
    if (targets.length === 0 || bulkRunRef.current) return;
    const selectionRequest = requestRef.current;
    bulkRunRef.current = true;
    setActionBusy(true);
    setActionError(null);
    try {
      const result = await bulkDeleteKnowledgeAssets({
        itemIds: targets.map((item) => item.id),
        scope: "personal",
        reason: deleteReason.trim() || undefined,
      });
      setDialogKind(null);
      await load();
      setNotice(
        `批量操作完成：提交 ${result.submitted}，成功 ${result.succeeded}，跳过 ${result.skipped}，失败 ${result.failed}`,
      );
    } catch (error) {
      const retryIds =
        error instanceof ControlledBulkRequestError
          ? new Set(error.retryItems as string[])
          : new Set(targets.map((item) => item.id));
      const partial = error instanceof ControlledBulkRequestError ? error.partialResult : null;
      const selectionScopeUnchanged = requestRef.current === selectionRequest;
      await load();
      if (selectionScopeUnchanged && requestRef.current === selectionRequest + 1) {
        setSelectedItems(targets.filter((item) => retryIds.has(item.id)));
      }
      setAllMatchingSelected(false);
      setDialogKind(null);
      setNotice(
        partial
          ? `批量操作中断：已完成提交 ${partial.submitted} 项（成功 ${partial.succeeded}，跳过 ${partial.skipped}，失败 ${partial.failed}），剩余 ${retryIds.size} 项可重试。`
          : `批量操作未开始，${retryIds.size} 项仍保留选择，可重试。`,
      );
    } finally {
      bulkRunRef.current = false;
      setActionBusy(false);
    }
  };

  const filtered = Boolean(
    assetType || personalState || sortBy !== "updated_at" || sortDirection !== "desc",
  );
  const forbidden = loadState === "forbidden";
  const hasProjects = projects.length > 0;
  return {
    forbidden,
    kbState,
    kb,
    actionBusy,
    createKb,
    setKbName,
    setDialogKind,
    notice,
    actionError,
    dialogKind,
    summary,
    personalState,
    setPersonalState,
    setPage,
    filtered,
    filterOpen,
    setFilterOpen,
    clearFilters,
    assetType,
    setAssetType,
    sortBy,
    sortDirection,
    setSortBy,
    setSortDirection,
    submitSearch,
    searchInput,
    setSearchInput,
    keyword,
    setKeyword,
    selectedItems,
    selectedPageItems,
    matchingSelectableItems,
    allMatchingSelected,
    matchingSelectionLoading,
    selectAllMatching,
    setSelectedItems,
    setAllMatchingSelected,
    selectedDeleteItems,
    setDeleteReason,
    setActionError,
    loadState,
    load,
    items,
    pageAllSelected,
    pageIndeterminate,
    selectablePageItems,
    loadMatchingSelectableItems,
    isBulkSelectable,
    openItemDialog,
    hasProjects,
    menuId,
    setMenuId,
    total,
    page,
    hasNext,
    closeDialog,
    kbName,
    models,
    renameKb,
    activeItem,
    runItemAction,
    targetProject,
    publicationPreview,
    publicationNaming,
    setTargetProject,
    setPublicationNaming,
    setPublicationPreview,
    projects,
    evidenceType,
    evidenceCategory,
    evidenceDescription,
    setEvidenceType,
    setEvidenceCategory,
    setEvidenceDescription,
    editTitle,
    editType,
    editTags,
    setEditTitle,
    setEditType,
    setEditTags,
    deleteReason,
    runPersonalBulkDelete,
  };
}
export type MyKnowledgeController = ReturnType<typeof useMyKnowledge>;
