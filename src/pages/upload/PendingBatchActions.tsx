import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Trash2 } from "lucide-react";
import ConfirmDialog from "../../components/ConfirmDialog";
import { ApiError } from "../../api/http";
import {
  classifyBatchNamingCategories,
  fetchNamingOptions,
  previewBatchIngestNaming,
  saveManualNamingCategory,
} from "../../api/naming";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type {
  BatchNamingPreviewItemDTO,
  BatchNamingValuesDTO,
  CategoryClassificationItemDTO,
  NamingOptionsDTO,
} from "../../types/naming";
import type { UploadFlow } from "./useUploadFlow";
import type { TargetLibrary } from "./uploadConstants";

type ReviewRows = Record<string, BatchNamingValuesDTO>;
type PreviewRows = Record<string, BatchNamingPreviewItemDTO>;
type ReviewFilter = "all" | "ai_ready" | "manual" | "reviewed" | "exception";
type ReviewState = Exclude<ReviewFilter, "all">;
type DeleteFeedback = { message: string; retryable: boolean };
type CompletedReviewItem = {
  taskId: string;
  title: string;
  assetId?: string;
};

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const VERSION_PATTERN = /^V[1-9]\d*(?:\.\d+)*$/;
const CONFIDENTIALITY_LEVELS = new Set(["L1", "L2", "L3", "L4", "L5"]);

function parsedValue(task: PendingIngestItemDTO, field: "date" | "version"): string {
  const parsed = task.naming_parsed_fields;
  if (!parsed || parsed.missing_fields?.includes(field)) return "";
  const value = parsed[field]?.trim() ?? "";
  if (field === "date") {
    if (DATE_PATTERN.test(value)) return value;
    if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}`;
    return "";
  }
  return VERSION_PATTERN.test(value.toUpperCase()) ? value.toUpperCase() : "";
}

function sourceSubject(task: PendingIngestItemDTO): string {
  // The original filename is displayed as source context only. Do not turn it
  // into a governed subject unless the backend has already projected a safe suggestion.
  return task.suggested_title?.trim() || "";
}

function suggestedVersion(task: PendingIngestItemDTO): string {
  const value = task.suggested_version?.trim().toUpperCase() ?? "";
  return VERSION_PATTERN.test(value) ? value : "V1";
}

function hasReliableAiConfidentiality(task: PendingIngestItemDTO): boolean {
  return (
    task.confidentiality_source === "ai_content" &&
    (task.confidentiality_confidence === "high" || task.confidentiality_confidence === "medium") &&
    CONFIDENTIALITY_LEVELS.has(task.suggested_confidentiality_level ?? "")
  );
}

function suggestedConfidentiality(task: PendingIngestItemDTO, options: NamingOptionsDTO): string {
  if (hasReliableAiConfidentiality(task)) return task.suggested_confidentiality_level!;
  return options.default_confidentiality || "L2";
}

function initialRows(
  tasks: PendingIngestItemDTO[],
  options: NamingOptionsDTO,
  suggestions: Record<string, CategoryClassificationItemDTO>,
): ReviewRows {
  return Object.fromEntries(
    tasks.map((task) => {
      const suggestion = suggestions[task.id];
      const categoryId =
        suggestion?.status === "classified" &&
        suggestion.suggested_category_id &&
        suggestion.candidate_rule_revision === options.rule_version &&
        options.categories.some((category) => category.id === suggestion.suggested_category_id)
          ? suggestion.suggested_category_id
          : "";
      return [
        task.id,
        {
          category_id: categoryId,
          subject: sourceSubject(task),
          formed_on: parsedValue(task, "date"),
          version: suggestedVersion(task),
          applicable_to: "",
          confidentiality_level: suggestedConfidentiality(task, options),
        },
      ];
    }),
  );
}

type NamingField = "subject" | "category_id" | "formed_on" | "version" | "applicable_to";

type RowError = { field: NamingField | null; message: string };

function rowMissing(row: BatchNamingValuesDTO, company: boolean): RowError | null {
  if (!row.subject.trim()) return { field: "subject", message: "请填写主题" };
  if (!row.category_id) return { field: "category_id", message: "请选择目录类别" };
  if (!DATE_PATTERN.test(row.formed_on)) {
    return { field: "formed_on", message: "请填写文件形成日期" };
  }
  if (!VERSION_PATTERN.test(row.version.toUpperCase())) {
    return { field: "version", message: "请填写有效版本，例如 V1" };
  }
  if (company && !row.applicable_to?.trim()) {
    return { field: "applicable_to", message: "请填写适用对象" };
  }
  return null;
}

function previewError(preview: BatchNamingPreviewItemDTO | undefined): RowError | null {
  if (!preview?.message || preview.submittable) return null;
  const fields: Partial<Record<string, NamingField>> = {
    naming_subject_invalid: "subject",
    naming_category_unavailable: "category_id",
    naming_formed_on_invalid: "formed_on",
    naming_version_invalid: "version",
    naming_applicable_to_required: "applicable_to",
  };
  return { field: fields[preview.error_code ?? ""] ?? null, message: preview.message };
}

function reviewState(
  task: PendingIngestItemDTO,
  row: BatchNamingValuesDTO,
  preview: BatchNamingPreviewItemDTO | undefined,
  company: boolean,
  flowError: string | undefined,
  edited: boolean,
  reviewed: boolean,
  categorySuggestion: CategoryClassificationItemDTO | undefined,
): ReviewState {
  if (preview?.error_code) return "exception";
  if (flowError) return "exception";
  if (rowMissing(row, company)) return "manual";
  if (reviewed) return "reviewed";
  if (edited) return "manual";

  const parsed = task.naming_parsed_fields;
  const legacyCategoryFields = new Set(["primary_category", "secondary_category"]);
  const unsafeAiField = Boolean(
    parsed &&
    [...(parsed.missing_fields ?? []), ...(parsed.inferred_fields ?? [])].some(
      (field) => !legacyCategoryFields.has(field),
    ),
  );
  const differsFromSafeAi =
    row.subject.trim() !== sourceSubject(task) ||
    row.category_id !== categorySuggestion?.suggested_category_id ||
    row.formed_on !== parsedValue(task, "date") ||
    row.version.toUpperCase() !== suggestedVersion(task);
  if (
    !parsed ||
    unsafeAiField ||
    categorySuggestion?.category_source !== "ai_content" ||
    (categorySuggestion.category_confidence !== "high" &&
      categorySuggestion.category_confidence !== "medium") ||
    differsFromSafeAi ||
    (task.version_source !== "source_filename" && task.version_source !== "ai_content") ||
    !hasReliableAiConfidentiality(task) ||
    (company && !row.applicable_to)
  ) {
    return "manual";
  }
  return "ai_ready";
}

export default function PendingBatchActions({
  tasks,
  flow,
}: {
  tasks: PendingIngestItemDTO[];
  flow: UploadFlow;
}) {
  const [rejectOpen, setRejectOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [stage, setStage] = useState<"target" | "review">("target");
  const [targetLibrary, setTargetLibrary] = useState<TargetLibrary>("");
  const [targetProjectId, setTargetProjectId] = useState("");
  const [options, setOptions] = useState<NamingOptionsDTO | null>(null);
  const [rows, setRows] = useState<ReviewRows>({});
  const [previews, setPreviews] = useState<PreviewRows>({});
  const [reviewTargetKey, setReviewTargetKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  const [deleteCandidate, setDeleteCandidate] = useState<PendingIngestItemDTO | null>(null);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [deleteFeedback, setDeleteFeedback] = useState<Record<string, DeleteFeedback>>({});
  const [editedTaskIds, setEditedTaskIds] = useState<Set<string>>(() => new Set());
  const [reviewedTaskIds, setReviewedTaskIds] = useState<Set<string>>(() => new Set());
  const [filterSnapshot, setFilterSnapshot] = useState<{
    filter: ReviewFilter;
    taskIds: string[];
  } | null>(null);
  const [previewBusyByTask, setPreviewBusyByTask] = useState<Record<string, boolean>>({});
  const [previewFeedback, setPreviewFeedback] = useState<Record<string, string>>({});
  const [confirmCandidate, setConfirmCandidate] = useState<PendingIngestItemDTO | null>(null);
  const [confirmingTaskId, setConfirmingTaskId] = useState<string | null>(null);
  const [categorySuggestions, setCategorySuggestions] = useState<
    Record<string, CategoryClassificationItemDTO>
  >({});
  const [categoryTargetLabel, setCategoryTargetLabel] = useState("");
  const [classificationBusy, setClassificationBusy] = useState(false);
  const [closeGuardOpen, setCloseGuardOpen] = useState(false);
  const [reviewTasks, setReviewTasks] = useState<PendingIngestItemDTO[]>([]);
  const [reviewInitialCount, setReviewInitialCount] = useState(0);
  const [completedReviewItems, setCompletedReviewItems] = useState<CompletedReviewItem[]>([]);
  const previewRunsRef = useRef<Record<string, number>>({});
  const previewTimersRef = useRef<Record<string, number>>({});

  const cancelPendingPreviews = () => {
    Object.values(previewTimersRef.current).forEach((timer) => window.clearTimeout(timer));
    Object.keys(previewTimersRef.current).forEach((taskId) => {
      delete previewTimersRef.current[taskId];
    });
    Object.keys(previewRunsRef.current).forEach((taskId) => {
      previewRunsRef.current[taskId] += 1;
    });
  };

  useEffect(() => {
    if (!confirmOpen) {
      cancelPendingPreviews();
    }
  }, [confirmOpen]);

  useEffect(() => {
    if (!confirmOpen) return;
    const liveTaskIds = new Set(tasks.map((task) => task.id));
    const vanishedTaskIds = new Set(
      reviewTasks.filter((task) => !liveTaskIds.has(task.id)).map((task) => task.id),
    );
    if (vanishedTaskIds.size === 0) return;

    vanishedTaskIds.forEach((taskId) => {
      const timer = previewTimersRef.current[taskId];
      if (timer) window.clearTimeout(timer);
      delete previewTimersRef.current[taskId];
      previewRunsRef.current[taskId] = (previewRunsRef.current[taskId] ?? 0) + 1;
    });
    const withoutVanished = <T,>(current: Record<string, T>) =>
      Object.fromEntries(
        Object.entries(current).filter(([taskId]) => !vanishedTaskIds.has(taskId)),
      ) as Record<string, T>;
    const withoutVanishedIds = (current: Set<string>) => {
      const next = new Set(current);
      vanishedTaskIds.forEach((taskId) => next.delete(taskId));
      return next;
    };

    setReviewTasks((current) => current.filter((task) => !vanishedTaskIds.has(task.id)));
    setRows(withoutVanished);
    setPreviews(withoutVanished);
    setDeleteFeedback(withoutVanished);
    setPreviewBusyByTask(withoutVanished);
    setPreviewFeedback(withoutVanished);
    setCategorySuggestions(withoutVanished);
    setEditedTaskIds(withoutVanishedIds);
    setReviewedTaskIds(withoutVanishedIds);
    setFilterSnapshot((current) =>
      current
        ? {
            ...current,
            taskIds: current.taskIds.filter((taskId) => !vanishedTaskIds.has(taskId)),
          }
        : null,
    );
    setDeleteCandidate((current) => (current && vanishedTaskIds.has(current.id) ? null : current));
    setConfirmCandidate((current) => (current && vanishedTaskIds.has(current.id) ? null : current));
  }, [confirmOpen, reviewTasks, tasks]);

  useEffect(() => {
    const timers = previewTimersRef.current;
    const runs = previewRunsRef.current;
    return () => {
      Object.values(timers).forEach((timer) => window.clearTimeout(timer));
      Object.keys(timers).forEach((taskId) => {
        delete timers[taskId];
      });
      Object.keys(runs).forEach((taskId) => {
        runs[taskId] += 1;
      });
    };
  }, []);

  const liveSelectedConfirmTasks = tasks.filter(
    (task) => flow.batchSelection.includes(task.id) && task.can_batch_confirm,
  );
  const selectedConfirmTasks = confirmOpen ? reviewTasks : liveSelectedConfirmTasks;
  const selectedRejectTasks = tasks.filter(
    (task) => flow.batchSelection.includes(task.id) && task.can_batch_reject,
  );
  const company = targetLibrary === "company";
  const categories = useMemo(() => options?.categories ?? [], [options]);
  const missingDates = selectedConfirmTasks.filter(
    (task) => !DATE_PATTERN.test(rows[task.id]?.formed_on ?? ""),
  ).length;
  const allPreviewed =
    stage === "review" &&
    selectedConfirmTasks.length > 0 &&
    selectedConfirmTasks.every(
      (task) =>
        Boolean(rows[task.id]) &&
        !rowMissing(rows[task.id], company) &&
        previews[task.id]?.submittable,
    );
  const targetReady =
    Boolean(targetLibrary) && (targetLibrary !== "project" || Boolean(targetProjectId));

  const targetKey = `${targetLibrary}:${targetProjectId}`;
  const statesByTask = useMemo(
    () =>
      Object.fromEntries(
        selectedConfirmTasks.flatMap((task) => {
          const row = rows[task.id];
          if (!row) return [];
          return [
            [
              task.id,
              reviewState(
                task,
                row,
                previews[task.id],
                company,
                flow.batchErrors[task.id],
                editedTaskIds.has(task.id),
                reviewedTaskIds.has(task.id),
                categorySuggestions[task.id],
              ),
            ],
          ];
        }),
      ) as Record<string, ReviewState>,
    [
      company,
      editedTaskIds,
      flow.batchErrors,
      previews,
      reviewedTaskIds,
      categorySuggestions,
      rows,
      selectedConfirmTasks,
    ],
  );
  const stateCounts = useMemo(
    () => ({
      all: selectedConfirmTasks.length,
      ai_ready: selectedConfirmTasks.filter((task) => statesByTask[task.id] === "ai_ready").length,
      manual: selectedConfirmTasks.filter((task) => statesByTask[task.id] === "manual").length,
      reviewed: selectedConfirmTasks.filter((task) => statesByTask[task.id] === "reviewed").length,
      exception: selectedConfirmTasks.filter((task) => statesByTask[task.id] === "exception")
        .length,
    }),
    [selectedConfirmTasks, statesByTask],
  );
  const visibleTaskIds =
    reviewFilter === "all"
      ? selectedConfirmTasks.map((task) => task.id)
      : filterSnapshot?.filter === reviewFilter
        ? filterSnapshot.taskIds
        : selectedConfirmTasks
            .filter((task) => statesByTask[task.id] === reviewFilter)
            .map((task) => task.id);
  const visibleConfirmTasks = selectedConfirmTasks.filter((task) =>
    visibleTaskIds.includes(task.id),
  );
  const previewSummary = useMemo(
    () =>
      `已核对 ${stateCounts.reviewed}/${selectedConfirmTasks.length} 条，仍有 ${missingDates} 条需补充形成日期`,
    [missingDates, selectedConfirmTasks.length, stateCounts.reviewed],
  );
  const warningNotices = selectedConfirmTasks.flatMap((task) => previews[task.id]?.notices ?? []);
  const warningCodesByTask = Object.fromEntries(
    selectedConfirmTasks.map((task) => [
      task.id,
      (previews[task.id]?.notices ?? []).flatMap((notice) => (notice.code ? [notice.code] : [])),
    ]),
  );

  if (
    !confirmOpen &&
    !rejectOpen &&
    liveSelectedConfirmTasks.length === 0 &&
    selectedRejectTasks.length === 0
  ) {
    return null;
  }

  const scheduleRowPreview = (taskId: string, row: BatchNamingValuesDTO) => {
    const previousTimer = previewTimersRef.current[taskId];
    if (previousTimer) window.clearTimeout(previousTimer);
    const runId = (previewRunsRef.current[taskId] ?? 0) + 1;
    previewRunsRef.current[taskId] = runId;
    const missing = rowMissing(row, company);
    if (missing) {
      setPreviewBusyByTask((current) => ({ ...current, [taskId]: false }));
      setPreviewFeedback((current) => ({ ...current, [taskId]: `${missing.message}后生成规范名` }));
      return;
    }
    if (targetLibrary !== "project" && targetLibrary !== "company") return;
    setPreviewBusyByTask((current) => ({ ...current, [taskId]: true }));
    setPreviewFeedback((current) => {
      const next = { ...current };
      delete next[taskId];
      return next;
    });
    previewTimersRef.current[taskId] = window.setTimeout(() => {
      delete previewTimersRef.current[taskId];
      void Promise.resolve()
        .then(() =>
          previewBatchIngestNaming({
            targetScope: targetLibrary,
            targetProjectId: targetProjectId || undefined,
            items: [{ taskId, naming: row }],
          }),
        )
        .then((response) => {
          if (previewRunsRef.current[taskId] !== runId) return;
          const preview = response?.items?.[0];
          if (!preview) throw new Error("empty naming preview response");
          setPreviews((current) => ({ ...current, [taskId]: preview }));
          const subject = preview.fields?.subject;
          if (typeof subject === "string" && subject !== row.subject) {
            setRows((current) => ({
              ...current,
              [taskId]: { ...current[taskId], subject },
            }));
          }
          if (!preview.submittable && preview.message) {
            setPreviewFeedback((current) => ({ ...current, [taskId]: preview.message! }));
          }
        })
        .catch((error) => {
          if (previewRunsRef.current[taskId] !== runId) return;
          setPreviewFeedback((current) => ({
            ...current,
            [taskId]:
              error instanceof ApiError
                ? error.message
                : "规范名预览暂时失败，请重试；已保留上一次有效预览",
          }));
        })
        .finally(() => {
          if (previewRunsRef.current[taskId] === runId) {
            setPreviewBusyByTask((current) => ({ ...current, [taskId]: false }));
          }
        });
    }, 250);
  };

  const updateRow = (taskId: string, patch: Partial<BatchNamingValuesDTO>) => {
    const nextRow = { ...rows[taskId], ...patch };
    setRows((current) => ({ ...current, [taskId]: nextRow }));
    // Keep the last canonical name visible as a reference, but revoke its submit
    // authority immediately. A fresh server preview is required for edited values.
    setPreviews((current) => {
      const previous = current[taskId];
      if (!previous?.submittable) return current;
      return { ...current, [taskId]: { ...previous, submittable: false } };
    });
    setEditedTaskIds((current) => new Set(current).add(taskId));
    setReviewedTaskIds((current) => {
      const next = new Set(current);
      next.delete(taskId);
      return next;
    });
    scheduleRowPreview(taskId, nextRow);
  };

  const selectManualCategory = (taskId: string, categoryId: string) => {
    updateRow(taskId, { category_id: categoryId });
    if (!categoryId || (targetLibrary !== "project" && targetLibrary !== "company")) return;
    setCategorySuggestions((current) => ({
      ...current,
      [taskId]: {
        task_id: taskId,
        suggested_category_id: categoryId,
        category_source: "manual",
        category_confidence: "high",
        category_reason: "人工已选择",
        candidate_rule_revision: options?.rule_version ?? null,
        status: "classified",
        retryable: false,
      },
    }));
    void saveManualNamingCategory({
      taskId,
      targetScope: targetLibrary,
      targetProjectId: targetProjectId || undefined,
      categoryId,
    }).catch((error) => {
      setPreviewFeedback((current) => ({
        ...current,
        [taskId]: error instanceof ApiError ? error.message : "人工目录类别暂未保存，请重试",
      }));
    });
  };

  const classifyCategories = async (retry: boolean) => {
    if (targetLibrary !== "project" && targetLibrary !== "company") return null;
    setClassificationBusy(true);
    try {
      const response = await classifyBatchNamingCategories({
        taskIds: selectedConfirmTasks.map((task) => task.id),
        targetScope: targetLibrary,
        targetProjectId: targetProjectId || undefined,
        retry,
      });
      const next = Object.fromEntries(response.items.map((item) => [item.task_id, item]));
      setCategorySuggestions(next);
      setCategoryTargetLabel(response.target_label);
      return next;
    } finally {
      setClassificationBusy(false);
    }
  };

  const confirmSingleDelete = async () => {
    const task = deleteCandidate;
    if (!task) return;
    const pendingTimer = previewTimersRef.current[task.id];
    if (pendingTimer) window.clearTimeout(pendingTimer);
    delete previewTimersRef.current[task.id];
    previewRunsRef.current[task.id] = (previewRunsRef.current[task.id] ?? 0) + 1;
    setDeletingTaskId(task.id);
    const result = await flow.handleDeleteBatchReviewItem(task.id);
    setDeletingTaskId(null);
    setDeleteCandidate(null);
    if (!result.ok) {
      setDeleteFeedback((current) => ({
        ...current,
        [task.id]: { message: result.message, retryable: result.retryable },
      }));
      return;
    }
    setReviewTasks((current) => current.filter((item) => item.id !== task.id));
    setRows((current) => {
      const next = { ...current };
      delete next[task.id];
      return next;
    });
    setPreviews((current) => {
      const next = { ...current };
      delete next[task.id];
      return next;
    });
    setDeleteFeedback((current) => {
      const next = { ...current };
      delete next[task.id];
      return next;
    });
  };

  const advanceTarget = async () => {
    if (!targetReady) return;
    if (targetLibrary === "personal") {
      closeAndResetReview();
      void flow.handleBatchConfirm(selectedConfirmTasks, "personal", undefined);
      return;
    }
    if (targetLibrary !== "project" && targetLibrary !== "company") return;
    const destination = targetLibrary;
    setLoading(true);
    setDialogError(null);
    try {
      const value = await fetchNamingOptions(destination, targetProjectId || undefined);
      if (!value.required) {
        const projectId = targetProjectId || undefined;
        closeAndResetReview();
        void flow.handleBatchConfirm(selectedConfirmTasks, destination, projectId);
        return;
      }
      setOptions(value);
      if (reviewTargetKey !== targetKey) {
        Object.values(previewTimersRef.current).forEach((timer) => window.clearTimeout(timer));
        Object.keys(previewTimersRef.current).forEach((taskId) => {
          delete previewTimersRef.current[taskId];
        });
        Object.keys(previewRunsRef.current).forEach((taskId) => {
          previewRunsRef.current[taskId] += 1;
        });
        const classified = await classifyCategories(false);
        const nextRows = initialRows(selectedConfirmTasks, value, classified ?? {});
        setRows(nextRows);
        setPreviews({});
        setEditedTaskIds(new Set());
        setReviewedTaskIds(new Set());
        setPreviewFeedback({});
        setReviewTargetKey(targetKey);
        selectedConfirmTasks.forEach((task) => scheduleRowPreview(task.id, nextRows[task.id]));
      }
      setStage("review");
    } catch (error) {
      setDialogError(error instanceof ApiError ? error.message : "命名规则暂时无法加载");
    } finally {
      setLoading(false);
    }
  };

  const retryCategoryClassifications = async () => {
    try {
      const classified = await classifyCategories(true);
      if (!classified) return;
      setRows((current) => {
        const next = { ...current };
        selectedConfirmTasks.forEach((task) => {
          if (editedTaskIds.has(task.id)) return;
          const item = classified[task.id];
          next[task.id] = {
            ...next[task.id],
            category_id:
              item?.status === "classified" && item.suggested_category_id
                ? item.suggested_category_id
                : "",
          };
        });
        return next;
      });
    } catch (error) {
      setDialogError(error instanceof ApiError ? error.message : "AI 目录分类暂时失败");
    }
  };

  const retryOneCategoryClassification = async (taskId: string) => {
    if (targetLibrary !== "project" && targetLibrary !== "company") return;
    setClassificationBusy(true);
    try {
      const response = await classifyBatchNamingCategories({
        taskIds: [taskId],
        targetScope: targetLibrary,
        targetProjectId: targetProjectId || undefined,
        retry: true,
      });
      const item = response.items[0];
      if (!item) return;
      setCategorySuggestions((current) => ({ ...current, [taskId]: item }));
      if (!editedTaskIds.has(taskId)) {
        setRows((current) => ({
          ...current,
          [taskId]: {
            ...current[taskId],
            category_id:
              item.status === "classified" && item.suggested_category_id
                ? item.suggested_category_id
                : "",
          },
        }));
      }
    } catch (error) {
      setPreviewFeedback((current) => ({
        ...current,
        [taskId]: error instanceof ApiError ? error.message : "AI 目录分类暂时失败",
      }));
    } finally {
      setClassificationBusy(false);
    }
  };

  const refreshPreviews = async () => {
    if (targetLibrary !== "project" && targetLibrary !== "company") return;
    setLoading(true);
    setDialogError(null);
    const refreshRuns: Record<string, number> = {};
    selectedConfirmTasks.forEach((task) => {
      previewRunsRef.current[task.id] = (previewRunsRef.current[task.id] ?? 0) + 1;
      refreshRuns[task.id] = previewRunsRef.current[task.id];
      const timer = previewTimersRef.current[task.id];
      if (timer) window.clearTimeout(timer);
    });
    try {
      const response = await previewBatchIngestNaming({
        targetScope: targetLibrary,
        targetProjectId: targetProjectId || undefined,
        items: selectedConfirmTasks.map((task) => ({ taskId: task.id, naming: rows[task.id] })),
      });
      const currentItems = response.items.filter(
        (item) => previewRunsRef.current[item.task_id] === refreshRuns[item.task_id],
      );
      setPreviews((current) => ({
        ...current,
        ...Object.fromEntries(currentItems.map((item) => [item.task_id, item])),
      }));
      setReviewedTaskIds(
        new Set(currentItems.filter((item) => item.submittable).map((item) => item.task_id)),
      );
      setRows((current) => {
        const updated = { ...current };
        currentItems.forEach((item) => {
          const subject = item.fields?.subject;
          if (typeof subject === "string" && updated[item.task_id]) {
            updated[item.task_id] = { ...updated[item.task_id], subject };
          }
        });
        return updated;
      });
    } catch (error) {
      setDialogError(
        error instanceof ApiError ? error.message : "批量预览暂时失败，资料仍保留，可稍后重试",
      );
    } finally {
      setLoading(false);
      setPreviewBusyByTask((current) => {
        const next = { ...current };
        selectedConfirmTasks.forEach((task) => {
          next[task.id] = false;
        });
        return next;
      });
    }
  };

  const confirmSingle = async () => {
    const task = confirmCandidate;
    if (
      !task ||
      confirmingTaskId ||
      deletingTaskId ||
      (targetLibrary !== "project" && targetLibrary !== "company")
    ) {
      return;
    }
    const row = rows[task.id];
    const missing = row ? rowMissing(row, company) : null;
    if (!row || missing || !previews[task.id]?.submittable) {
      setPreviewFeedback((current) => ({
        ...current,
        [task.id]: missing?.message ?? "请先生成有效的规范名预览",
      }));
      setConfirmCandidate(null);
      return;
    }
    setConfirmingTaskId(task.id);
    const result = await flow.handleSingleBatchConfirm(
      task,
      targetLibrary,
      targetProjectId || undefined,
      row,
      warningCodesByTask[task.id] ?? [],
    );
    setConfirmingTaskId(null);
    setConfirmCandidate(null);
    if (result.succeededIds.includes(task.id)) {
      const completedTitle =
        row.subject.trim() || task.suggested_title?.trim() || task.source_file_name;
      setCompletedReviewItems((current) => [
        ...current.filter((item) => item.taskId !== task.id),
        {
          taskId: task.id,
          title: completedTitle,
          assetId: result.resultAssetIds?.[task.id],
        },
      ]);
      setReviewTasks((current) => current.filter((item) => item.id !== task.id));
      setRows((current) => {
        const next = { ...current };
        delete next[task.id];
        return next;
      });
      setPreviews((current) => {
        const next = { ...current };
        delete next[task.id];
        return next;
      });
      setEditedTaskIds((current) => {
        const next = new Set(current);
        next.delete(task.id);
        return next;
      });
      setReviewedTaskIds((current) => {
        const next = new Set(current);
        next.delete(task.id);
        return next;
      });
      return;
    }
    setPreviewFeedback((current) => ({
      ...current,
      [task.id]: "确认未完成，资料仍保留，请根据提示修改后重试",
    }));
  };

  const submitGovernedBatch = () => {
    if (
      !allPreviewed ||
      flow.batchBusy ||
      (targetLibrary !== "project" && targetLibrary !== "company")
    ) {
      return;
    }
    const destination = targetLibrary;
    const projectId = targetProjectId || undefined;
    const submittedRows = Object.fromEntries(
      selectedConfirmTasks.map((task) => [task.id, rows[task.id]]),
    );
    void flow.handleBatchConfirm(
      selectedConfirmTasks,
      destination,
      projectId,
      submittedRows,
      warningCodesByTask,
      true,
      (result) => {
        if (result.failedIds.length === 0) {
          closeAndResetReview();
          return;
        }
        const succeeded = new Set(result.succeededIds);
        const completed = selectedConfirmTasks
          .filter((task) => succeeded.has(task.id))
          .map((task) => ({
            taskId: task.id,
            title:
              rows[task.id]?.subject.trim() ||
              task.suggested_title?.trim() ||
              task.source_file_name,
            assetId: result.resultAssetIds?.[task.id],
          }));
        setCompletedReviewItems((current) => [
          ...current.filter((item) => !succeeded.has(item.taskId)),
          ...completed,
        ]);
        setReviewTasks((current) => current.filter((task) => !succeeded.has(task.id)));
        setDialogError(
          `${result.failedIds.length} 项资料确认未完成，已保留本次核对内容，请根据行内提示修正后重试。`,
        );
      },
    );
  };

  const closeAndResetReview = () => {
    cancelPendingPreviews();
    setConfirmOpen(false);
    setCloseGuardOpen(false);
    setStage("target");
    setTargetLibrary("");
    setTargetProjectId("");
    setOptions(null);
    setRows({});
    setPreviews({});
    setReviewTargetKey("");
    setReviewFilter("all");
    setFilterSnapshot(null);
    setEditedTaskIds(new Set());
    setReviewedTaskIds(new Set());
    setPreviewBusyByTask({});
    setPreviewFeedback({});
    setCategorySuggestions({});
    setCategoryTargetLabel("");
    setDialogError(null);
    setReviewTasks([]);
    setReviewInitialCount(0);
    setCompletedReviewItems([]);
  };

  const requestCloseReview = () => {
    const previewInProgress = Object.values(previewBusyByTask).some(Boolean);
    if (editedTaskIds.size > 0 || previewInProgress || classificationBusy || confirmingTaskId) {
      setCloseGuardOpen(true);
      return;
    }
    closeAndResetReview();
  };

  return (
    <>
      <div className="upload77-batch-actions">
        {selectedConfirmTasks.length > 0 && (
          <button
            className="btn-primary"
            disabled={flow.batchBusy}
            onClick={() => {
              setReviewTasks(liveSelectedConfirmTasks);
              setReviewInitialCount(liveSelectedConfirmTasks.length);
              setCompletedReviewItems([]);
              setStage("target");
              setReviewFilter("all");
              setFilterSnapshot(null);
              setTargetLibrary("");
              setTargetProjectId("");
              setDialogError(null);
              setConfirmOpen(true);
            }}
            type="button"
          >
            {flow.batchBusy && flow.batchOperation === "confirm"
              ? "正在逐条确认"
              : `批量确认入库（${selectedConfirmTasks.length}）`}
          </button>
        )}
        {selectedRejectTasks.length > 0 && (
          <button
            className="btn-secondary upload77-batch-reject"
            disabled={flow.batchBusy}
            onClick={() => setRejectOpen(true)}
            type="button"
          >
            批量拒绝入库（{selectedRejectTasks.length}）
          </button>
        )}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title={
          stage === "target"
            ? `确认入库 ${selectedConfirmTasks.length} 项资料`
            : `逐条核对 ${reviewInitialCount} 项规范命名`
        }
        description={
          stage === "target"
            ? "请选择一个明确的目标知识库；取消不会创建资产或改变任务状态。"
            : undefined
        }
        confirmText={
          stage === "review" || targetLibrary === "personal" || !targetLibrary
            ? warningNotices.length > 0
              ? `仍然确认已选择的 ${selectedConfirmTasks.length} 项入库`
              : `确认已选择的 ${selectedConfirmTasks.length} 项入库`
            : "下一步：核对命名"
        }
        busyText={
          stage === "target"
            ? "正在加载规则"
            : flow.batchBusy && flow.batchOperation === "confirm"
              ? "正在提交"
              : "正在核对"
        }
        busy={loading || (flow.batchBusy && flow.batchOperation === "confirm")}
        confirmDisabled={stage === "target" ? !targetReady : !allPreviewed}
        error={dialogError}
        errorDescription={dialogError}
        panelClassName={stage === "review" ? "upload77-batch-naming-dialog" : undefined}
        closeButtonLabel={stage === "review" ? "关闭批量命名核对" : undefined}
        onCancel={requestCloseReview}
        onConfirm={stage === "target" ? () => void advanceTarget() : submitGovernedBatch}
      >
        {stage === "target" ? (
          <>
            <label className="upload77-field">
              <span>目标知识库</span>
              <select
                aria-label="批量入库目标知识库"
                value={targetLibrary}
                onChange={(event) => {
                  setTargetLibrary(event.target.value as TargetLibrary);
                  setTargetProjectId("");
                }}
              >
                <option value="">请选择目标知识库</option>
                <option value="personal">个人知识库</option>
                {(flow.projects ?? []).length > 0 && <option value="project">项目知识库</option>}
                {flow.canUseCompanyTarget && <option value="company">公司知识库</option>}
              </select>
            </label>
            {targetLibrary === "project" && (
              <label className="upload77-field">
                <span>具体项目</span>
                <select
                  aria-label="批量入库目标项目"
                  value={targetProjectId}
                  onChange={(event) => setTargetProjectId(event.target.value)}
                >
                  <option value="">请选择目标项目</option>
                  {(flow.projects ?? []).map((project) => (
                    <option key={project.projectId} value={project.projectId}>
                      {project.projectName}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </>
        ) : (
          <div className="upload77-batch-naming-review">
            <div className="upload77-batch-naming-toolbar">
              <div>
                <span role="status">{previewSummary}</span>
                <span className="upload77-batch-filter-summary" role="status">
                  当前筛选显示 {visibleConfirmTasks.length}/{selectedConfirmTasks.length} 条
                </span>
                {categoryTargetLabel && (
                  <span className="upload77-batch-filter-summary" role="status">
                    目录候选来自：{categoryTargetLabel}
                  </span>
                )}
              </div>
              <div className="upload77-batch-naming-row-actions">
                <button
                  className="btn-secondary"
                  disabled={loading || classificationBusy}
                  onClick={() => void retryCategoryClassifications()}
                  type="button"
                >
                  {classificationBusy ? "正在分类…" : "重试待分类项"}
                </button>
                <button
                  className="btn-secondary"
                  disabled={loading}
                  onClick={() => void refreshPreviews()}
                  type="button"
                >
                  生成或刷新全部预览
                </button>
              </div>
            </div>
            <div className="upload77-batch-naming-filters" aria-label="核对状态筛选">
              {(
                [
                  ["all", "全部"],
                  ["ai_ready", "AI 已确定"],
                  ["manual", "需人工补齐"],
                  ["reviewed", "已核对"],
                  ["exception", "异常/重复"],
                ] as const
              ).map(([value, label]) => (
                <button
                  aria-pressed={reviewFilter === value}
                  className="upload77-batch-filter"
                  key={value}
                  onClick={() => {
                    setReviewFilter(value);
                    setFilterSnapshot({
                      filter: value,
                      taskIds:
                        value === "all"
                          ? selectedConfirmTasks.map((task) => task.id)
                          : selectedConfirmTasks
                              .filter((task) => statesByTask[task.id] === value)
                              .map((task) => task.id),
                    });
                  }}
                  type="button"
                >
                  {label}（{stateCounts[value]}）
                </button>
              ))}
            </div>
            <div className="upload77-batch-naming-scroll">
              {completedReviewItems.length > 0 && (
                <section
                  className="upload77-batch-completed"
                  aria-labelledby="batch-completed-title"
                >
                  <h4 id="batch-completed-title">本次已入库（{completedReviewItems.length}）</h4>
                  <div className="upload77-batch-completed-list">
                    {completedReviewItems.map((item) => (
                      <article className="upload77-batch-completed-item" key={item.taskId}>
                        <div>
                          <strong>{item.title}</strong>
                          <span role="status">
                            {item.assetId ? "已入库" : "已提交，等待后续处理"}
                          </span>
                        </div>
                        {item.assetId && (
                          <a
                            aria-label={`查看知识资产卡片：${item.title}`}
                            className="btn-secondary"
                            href={`/knowledge/${encodeURIComponent(item.assetId)}`}
                            rel="noopener noreferrer"
                            target="_blank"
                          >
                            查看知识资产卡片
                          </a>
                        )}
                      </article>
                    ))}
                  </div>
                </section>
              )}
              {warningNotices.length > 0 && (
                <div className="upload77-batch-naming-notice" role="status">
                  当前批次有 {warningNotices.length}{" "}
                  项命名或重复风险提示；确认后将作为独立资料入库， 不会覆盖已有资产。
                </div>
              )}
              {visibleConfirmTasks.length === 0 && (
                <div className="upload77-batch-filter-empty" role="status">
                  {selectedConfirmTasks.length === 0
                    ? "本批待核对资料已处理完成，可查看本次结果或关闭弹窗"
                    : "当前筛选下没有资料"}
                </div>
              )}
              {visibleConfirmTasks.map((task) => {
                const row = rows[task.id];
                const preview = previews[task.id];
                if (!row) return null;
                const localError = rowMissing(row, company);
                const serverError = previewError(preview);
                const fieldError = localError ?? serverError;
                const categorySuggestion = categorySuggestions[task.id];
                return (
                  <article className="upload77-batch-naming-row" key={task.id}>
                    <header>
                      <strong title={task.source_file_name}>
                        {selectedConfirmTasks.indexOf(task) + 1}. {task.source_file_name}
                      </strong>
                      <div className="upload77-batch-naming-row-actions">
                        <span>
                          {preview?.submittable
                            ? editedTaskIds.has(task.id)
                              ? "可确认"
                              : "已核对"
                            : "待核对"}
                        </span>
                        <button
                          aria-label={`确认入库 ${task.source_file_name}`}
                          className="btn-primary upload77-batch-confirm-one"
                          disabled={
                            flow.batchBusy ||
                            deletingTaskId !== null ||
                            Boolean(rowMissing(row, company)) ||
                            !preview?.submittable
                          }
                          onClick={() => setConfirmCandidate(task)}
                          type="button"
                        >
                          <Check aria-hidden="true" size={14} />
                          确认入库
                        </button>
                        <button
                          aria-label={`删除 ${task.source_file_name}`}
                          className="upload77-batch-delete"
                          disabled={
                            !task.can_batch_reject ||
                            flow.batchBusy ||
                            confirmingTaskId !== null ||
                            deletingTaskId === task.id
                          }
                          onClick={() => {
                            setDeleteFeedback((current) => {
                              const next = { ...current };
                              delete next[task.id];
                              return next;
                            });
                            setDeleteCandidate(task);
                          }}
                          title={
                            task.can_batch_reject ? "永久删除错误上传资料" : "当前资料不能永久删除"
                          }
                          type="button"
                        >
                          <Trash2 aria-hidden="true" size={14} />
                          删除
                        </button>
                      </div>
                    </header>
                    {deleteFeedback[task.id] && (
                      <div className="upload77-batch-delete-error" role="alert">
                        <span>{deleteFeedback[task.id].message}</span>
                        {deleteFeedback[task.id].retryable && (
                          <button onClick={() => setDeleteCandidate(task)} type="button">
                            重试删除
                          </button>
                        )}
                      </div>
                    )}
                    <div className="upload77-batch-naming-grid">
                      <label>
                        <span>主题</span>
                        <input
                          aria-label={`${task.source_file_name} 主题`}
                          value={row.subject}
                          onChange={(event) => updateRow(task.id, { subject: event.target.value })}
                        />
                        {fieldError?.field === "subject" && (
                          <small className="upload77-batch-naming-error">
                            {fieldError.message}
                          </small>
                        )}
                      </label>
                      <label>
                        <span>目录类别</span>
                        <select
                          aria-label={`${task.source_file_name} 目录类别`}
                          value={row.category_id}
                          onChange={(event) => selectManualCategory(task.id, event.target.value)}
                        >
                          <option value="">请选择</option>
                          {categories.map((category) => (
                            <option key={category.id} value={category.id}>
                              {category.primary} / {category.secondary}
                            </option>
                          ))}
                        </select>
                        {fieldError?.field === "category_id" && (
                          <small className="upload77-batch-naming-error">
                            {fieldError.message}
                          </small>
                        )}
                        {categorySuggestion?.category_source === "ai_content" &&
                          categorySuggestion.suggested_category_id === row.category_id && (
                            <small className="upload77-batch-naming-notice">
                              AI 内容建议（
                              {categorySuggestion.category_confidence === "high" ? "高" : "中"}
                              置信度）
                            </small>
                          )}
                        {categorySuggestion?.category_source === "rule_only_option" &&
                          categorySuggestion.suggested_category_id === row.category_id && (
                            <small className="upload77-batch-naming-notice">规则唯一选项</small>
                          )}
                        {categorySuggestion?.category_source === "manual" && (
                          <small className="upload77-batch-naming-notice">人工已选择</small>
                        )}
                        {(!categorySuggestion ||
                          categorySuggestion.category_source === "needs_manual") && (
                          <small className="upload77-batch-naming-error">
                            {categorySuggestion?.category_reason ?? "尚未按当前规则分类"}
                            {categorySuggestion?.retryable && (
                              <button
                                disabled={classificationBusy || editedTaskIds.has(task.id)}
                                onClick={() => void retryOneCategoryClassification(task.id)}
                                type="button"
                              >
                                重试此项
                              </button>
                            )}
                          </small>
                        )}
                      </label>
                      <label>
                        <span>文件形成日期</span>
                        <input
                          aria-label={`${task.source_file_name} 文件形成日期`}
                          type="date"
                          value={row.formed_on}
                          onChange={(event) =>
                            updateRow(task.id, { formed_on: event.target.value })
                          }
                        />
                        {fieldError?.field === "formed_on" && (
                          <small className="upload77-batch-naming-error">
                            {fieldError.message}
                          </small>
                        )}
                      </label>
                      <label>
                        <span>版本</span>
                        <input
                          aria-label={`${task.source_file_name} 版本`}
                          placeholder="V1"
                          value={row.version}
                          onChange={(event) =>
                            updateRow(task.id, { version: event.target.value.toUpperCase() })
                          }
                        />
                        {fieldError?.field === "version" && (
                          <small className="upload77-batch-naming-error">
                            {fieldError.message}
                          </small>
                        )}
                        <small
                          className={`upload77-batch-naming-source ${
                            row.version !== suggestedVersion(task) ||
                            task.version_source === "default_needs_confirmation" ||
                            !task.version_source
                              ? "is-manual"
                              : ""
                          }`}
                        >
                          {row.version !== suggestedVersion(task)
                            ? "已人工修改"
                            : task.version_source === "source_filename"
                              ? "来自源文件"
                              : task.version_source === "ai_content"
                                ? "AI 建议"
                                : "规则默认，需核对"}
                        </small>
                      </label>
                      {company && (
                        <label>
                          <span>适用对象</span>
                          <input
                            aria-label={`${task.source_file_name} 适用对象`}
                            value={row.applicable_to ?? ""}
                            onChange={(event) =>
                              updateRow(task.id, { applicable_to: event.target.value })
                            }
                          />
                          {fieldError?.field === "applicable_to" && (
                            <small className="upload77-batch-naming-error">
                              {fieldError.message}
                            </small>
                          )}
                        </label>
                      )}
                      <label>
                        <span>密级</span>
                        <select
                          aria-label={`${task.source_file_name} 密级`}
                          value={row.confidentiality_level}
                          onChange={(event) =>
                            updateRow(task.id, { confidentiality_level: event.target.value })
                          }
                        >
                          {["L1", "L2", "L3", "L4", "L5"].map((level) => (
                            <option key={level}>{level}</option>
                          ))}
                        </select>
                        <small
                          className={`upload77-batch-naming-source ${
                            row.confidentiality_level !==
                              suggestedConfidentiality(task, options!) ||
                            !hasReliableAiConfidentiality(task)
                              ? "is-manual"
                              : ""
                          }`}
                          title={task.confidentiality_reason ?? undefined}
                        >
                          {row.confidentiality_level !== suggestedConfidentiality(task, options!)
                            ? "已人工修改"
                            : hasReliableAiConfidentiality(task)
                              ? `AI 内容建议 · ${
                                  task.confidentiality_confidence === "high" ? "高" : "中"
                                }置信度`
                              : "AI 未确定，规则默认，需核对"}
                        </small>
                      </label>
                    </div>
                    <div
                      className="upload77-batch-naming-preview"
                      title={preview?.canonical_name ?? undefined}
                    >
                      <strong>规范名预览：</strong>
                      {rowMissing(row, company)?.message
                        ? `${rowMissing(row, company)!.message}后生成规范名`
                        : previewBusyByTask[task.id]
                          ? "正在按当前填写内容生成…"
                          : (preview?.canonical_name ?? "正在准备规范名预览")}
                    </div>
                    {previewFeedback[task.id] && (
                      <div className="upload77-batch-naming-error" role="alert">
                        {previewFeedback[task.id]}
                        {!localError && (
                          <button
                            className="upload77-batch-preview-retry"
                            onClick={() => scheduleRowPreview(task.id, row)}
                            type="button"
                          >
                            重试预览
                          </button>
                        )}
                      </div>
                    )}
                    {serverError?.field === null && (
                      <div className="upload77-batch-naming-error">{serverError.message}</div>
                    )}
                    {preview?.notices.map((notice) => (
                      <div
                        className="upload77-batch-naming-notice"
                        key={`${notice.kind}-${notice.message}`}
                      >
                        {notice.message}
                      </div>
                    ))}
                  </article>
                );
              })}
            </div>
          </div>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={closeGuardOpen}
        title="放弃本次批量命名核对？"
        description="存在未保存修改或仍在进行的本地预览。关闭后将清理这些状态，已选择的待确认资料不会被删除。"
        confirmText="放弃修改并关闭"
        onCancel={() => setCloseGuardOpen(false)}
        onConfirm={closeAndResetReview}
      />

      <ConfirmDialog
        open={confirmCandidate !== null}
        title="确认将这条资料入库？"
        description={
          confirmCandidate
            ? `${previews[confirmCandidate.id]?.canonical_name ?? "规范名待校验"} · ${
                targetLibrary === "project" ? "项目知识库" : "公司知识库"
              }`
            : undefined
        }
        confirmText={
          confirmCandidate && (previews[confirmCandidate.id]?.notices.length ?? 0) > 0
            ? "仍然确认入库"
            : "确认入库"
        }
        busyText="正在确认入库"
        busy={confirmingTaskId !== null}
        onCancel={() => setConfirmCandidate(null)}
        onConfirm={() => void confirmSingle()}
      >
        {confirmCandidate && (previews[confirmCandidate.id]?.notices.length ?? 0) > 0 && (
          <div className="upload77-batch-naming-notice">
            <strong>请确认以下提示：</strong>
            {(previews[confirmCandidate.id]?.notices ?? []).map((notice) => (
              <div key={`${notice.code ?? notice.kind}-${notice.message}`}>{notice.message}</div>
            ))}
            <p>继续后会创建独立资料，不会覆盖已有资产。</p>
          </div>
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={deleteCandidate !== null}
        title="永久删除这条错误上传资料？"
        description="确认后将永久删除该错误上传资料，不会创建知识资产，操作不可恢复。"
        confirmText="确认永久删除"
        busyText="正在永久删除"
        busy={deletingTaskId !== null}
        danger
        onCancel={() => setDeleteCandidate(null)}
        onConfirm={() => void confirmSingleDelete()}
      />

      <ConfirmDialog
        open={rejectOpen}
        title={`永久拒绝选中的 ${selectedRejectTasks.length} 条待确认任务？`}
        description={`确认后将严格逐条删除这 ${selectedRejectTasks.length} 条待确认任务，操作不可恢复，且不会创建知识资产。`}
        confirmText="确认永久拒绝"
        busyText="正在逐条拒绝"
        busy={flow.batchBusy && flow.batchOperation === "reject"}
        danger
        onCancel={() => setRejectOpen(false)}
        onConfirm={() => {
          setRejectOpen(false);
          void flow.handleBatchReject(selectedRejectTasks);
        }}
      />
    </>
  );
}
