import { useEffect, useMemo, useRef, useState } from "react";
import type { PendingIngestItemDTO, UploadDuplicateDTO } from "../../types/ingest";
import type { BatchNamingValuesDTO } from "../../types/naming";
import {
  commandErrorMatches,
  commandErrorMessage,
  decideUploadDuplicate,
  previewBatchIngestNaming,
  previewIngestNaming,
} from "./pendingBatchCommands";
import { DATE_PATTERN, initialRows, reviewState, rowMissing } from "./pendingBatchReviewState";
import type {
  CompletedReviewItem,
  DeleteFeedback,
  PreviewRows,
  ReviewFilter,
  ReviewRows,
  ReviewState,
} from "./pendingBatchReviewState";
import { usePendingBatchAiReview } from "./usePendingBatchAiReview";
import { usePendingBatchTargetOptions } from "./usePendingBatchTargetOptions";
import type { TargetLibrary } from "./uploadConstants";
import type { UploadFlow } from "./useUploadFlow";

const EMPTY_DUPLICATE: UploadDuplicateDTO = {
  duplicate_state: "none",
  match_type: "none",
  match_count: 0,
  preferred_candidate: null,
  same_batch_group_id: null,
  same_batch_first_ordinal: null,
  default_selected: true,
  decision: null,
};

export function usePendingBatchReviewController(tasks: PendingIngestItemDTO[], flow: UploadFlow) {
  const [rejectOpen, setRejectOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [stage, setStage] = useState<"target" | "review">("target");
  const [targetLibrary, setTargetLibrary] = useState<TargetLibrary>("");
  const [targetProjectId, setTargetProjectId] = useState("");
  const targetOptions = usePendingBatchTargetOptions({
    open: confirmOpen,
    stage,
    targetLibrary,
    targetProjectId,
  });
  const { options, setOptions, busy: targetOptionsBusy, error: targetOptionsError } = targetOptions;
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
  const [bulkDirectoryKey, setBulkDirectoryKey] = useState("");
  const [bulkPersonalDirectoryKey, setBulkPersonalDirectoryKey] = useState("");
  const [personalDirectoryByTask, setPersonalDirectoryByTask] = useState<Record<string, string>>(
    {},
  );
  const [fallbackDirectoryTaskId, setFallbackDirectoryTaskId] = useState<string | null>(null);
  const [fallbackDirectoryKey, setFallbackDirectoryKey] = useState("");
  const aiReview = usePendingBatchAiReview();
  const aiReviewDrafts = aiReview.drafts;
  const [closeGuardOpen, setCloseGuardOpen] = useState(false);
  const [reviewTasks, setReviewTasks] = useState<PendingIngestItemDTO[]>([]);
  const [reviewInitialCount, setReviewInitialCount] = useState(0);
  const [completedReviewItems, setCompletedReviewItems] = useState<CompletedReviewItem[]>([]);
  const [personalDuplicates, setPersonalDuplicates] = useState<Record<string, UploadDuplicateDTO>>(
    {},
  );
  const [duplicateDecisionTaskId, setDuplicateDecisionTaskId] = useState<string | null>(null);
  const [skippedDuplicateItems, setSkippedDuplicateItems] = useState<
    import("./pendingBatchReviewState").SkippedDuplicateItem[]
  >([]);
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
    const withoutVanished = <T>(current: Record<string, T>) =>
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
    setPersonalDirectoryByTask(withoutVanished);
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
  const formalDirectories = useMemo(
    () =>
      (options?.directories ?? []).filter(
        (item) =>
          item.enabled !== false &&
          item.scope === targetLibrary &&
          item.directory_key !== "personal.pending",
      ),
    [options, targetLibrary],
  );
  const directoryLabel = (directoryKey: string) =>
    formalDirectories.find((item) => item.directory_key === directoryKey)?.display_name ?? "";
  const missingDates = selectedConfirmTasks.filter(
    (task) => !DATE_PATTERN.test(rows[task.id]?.formed_on ?? ""),
  ).length;
  const duplicateReady = (task: PendingIngestItemDTO) => {
    const duplicate =
      targetLibrary === "personal" ? personalDuplicates[task.id] : previews[task.id]?.duplicate;
    if (!duplicate || duplicate.duplicate_state === "none") return true;
    if (duplicate.duplicate_state === "suspected_metadata") return true;
    if (duplicate.decision === "independent") return true;
    return duplicate.duplicate_state === "same_batch" && duplicate.default_selected;
  };
  const allPreviewed =
    stage === "review" &&
    selectedConfirmTasks.length > 0 &&
    (targetLibrary === "personal"
      ? selectedConfirmTasks.every(
          (task) => Boolean(personalDirectoryByTask[task.id]) && duplicateReady(task),
        )
      : selectedConfirmTasks.every(
          (task) =>
            Boolean(rows[task.id]) &&
            !rowMissing(rows[task.id], company) &&
            previews[task.id]?.submittable &&
            duplicateReady(task),
        ));
  const targetReady =
    Boolean(targetLibrary) &&
    (targetLibrary !== "project" || Boolean(targetProjectId)) &&
    (targetLibrary !== "personal" ||
      (!targetOptionsBusy &&
        !targetOptionsError &&
        Boolean(bulkPersonalDirectoryKey) &&
        formalDirectories.some((item) => item.directory_key === bulkPersonalDirectoryKey)));

  const targetKey = `${targetLibrary}:${targetProjectId}:${bulkPersonalDirectoryKey}`;

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
            [taskId]: commandErrorMessage(
              error,
              "规范名预览暂时失败，请重试；已保留上一次有效预览",
            ),
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

  const resetTargetReviewContext = () => {
    targetOptions.reset();
    cancelPendingPreviews();
    setOptions(null);
    setBulkDirectoryKey("");
    setBulkPersonalDirectoryKey("");
    setPersonalDirectoryByTask({});
    setFallbackDirectoryTaskId(null);
    setFallbackDirectoryKey("");
    setRows({});
    setPreviews({});
    setReviewTargetKey("");
    setEditedTaskIds(new Set());
    setReviewedTaskIds(new Set());
    setSkippedDuplicateItems([]);
    aiReview.reset();
  };

  const loadAiReview = aiReview.open;

  const saveAiReviewDraft = () => {
    const saved = aiReview.saveDraft();
    if (!saved) return;
    if (targetLibrary !== "personal" && saved.draft.title) {
      updateRow(saved.taskId, { subject: saved.draft.title });
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
      if (
        !formalDirectories.some((directory) => directory.directory_key === bulkPersonalDirectoryKey)
      ) {
        setDialogError("请选择正式个人目录");
        return;
      }
      setPersonalDirectoryByTask(
        Object.fromEntries(selectedConfirmTasks.map((task) => [task.id, bulkPersonalDirectoryKey])),
      );
      setLoading(true);
      try {
        const values = await Promise.all(
          selectedConfirmTasks.map(
            async (task) =>
              [
                task.id,
                (
                  await previewIngestNaming(task.id, {
                    target_scope: "personal",
                    confidentiality_level: task.suggested_confidentiality_level ?? "L2",
                  })
                ).duplicate ??
                  task.duplicate ??
                  EMPTY_DUPLICATE,
              ] as const,
          ),
        );
        setPersonalDuplicates(Object.fromEntries(values));
      } catch (error) {
        setDialogError(commandErrorMessage(error, "重复状态暂时无法核对，请重试"));
        return;
      } finally {
        setLoading(false);
      }
      setReviewTargetKey(targetKey);
      setStage("review");
      return;
    }
    if (targetLibrary !== "project" && targetLibrary !== "company") return;
    const destination = targetLibrary;
    setLoading(true);
    setDialogError(null);
    try {
      const value = options ?? (await targetOptions.get(destination, targetProjectId || undefined));
      if (!value.required) {
        const projectId = targetProjectId || undefined;
        closeAndResetReview();
        void flow.handleBatchConfirm(selectedConfirmTasks, destination, projectId);
        return;
      }
      setOptions(value);
      if (value.directories.length === 0) {
        setDialogError(
          destination === "project"
            ? "当前没有可用的正式项目目录，请联系治理管理员配置并发布规则。"
            : "当前没有可用的正式公司目录，请联系治理管理员配置并发布规则。",
        );
        return;
      }
      if (reviewTargetKey !== targetKey) {
        Object.values(previewTimersRef.current).forEach((timer) => window.clearTimeout(timer));
        Object.keys(previewTimersRef.current).forEach((taskId) => {
          delete previewTimersRef.current[taskId];
        });
        Object.keys(previewRunsRef.current).forEach((taskId) => {
          previewRunsRef.current[taskId] += 1;
        });
        const nextRows = initialRows(selectedConfirmTasks, value);
        if (bulkDirectoryKey) {
          selectedConfirmTasks.forEach((task) => {
            nextRows[task.id].directory_key = bulkDirectoryKey;
          });
        }
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
      setDialogError(
        commandErrorMatches(error, { deniedReason: "project_naming_code_unavailable" })
          ? "目标项目尚未启用项目代码。请到项目设置完成项目代码后，返回此窗口重新加载规则。"
          : commandErrorMessage(error, "命名规则暂时无法加载，请重试"),
      );
    } finally {
      setLoading(false);
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
      setDialogError(commandErrorMessage(error, "批量预览暂时失败，资料仍保留，可稍后重试"));
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
    const singleDraft = aiReviewDrafts[task.id];
    const result = singleDraft
      ? await flow.handleSingleBatchConfirm(
          task,
          targetLibrary,
          targetProjectId || undefined,
          row,
          warningCodesByTask[task.id] ?? [],
          singleDraft,
        )
      : await flow.handleSingleBatchConfirm(
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
          indexStatus: result.resultIndexStatuses?.[task.id],
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

  const submitBatchReview = () => {
    if (
      !allPreviewed ||
      flow.batchBusy ||
      (targetLibrary !== "personal" && targetLibrary !== "project" && targetLibrary !== "company")
    ) {
      return;
    }
    const destination = targetLibrary;
    const projectId = targetProjectId || undefined;
    const submittedRows =
      destination === "personal"
        ? undefined
        : Object.fromEntries(selectedConfirmTasks.map((task) => [task.id, rows[task.id]]));
    const onCompleted = (result: {
      succeededIds: string[];
      failedIds: string[];
      resultAssetIds?: Record<string, string>;
      resultIndexStatuses?: Record<string, string>;
    }) => {
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
            aiReviewDrafts[task.id]?.title.trim() ||
            rows[task.id]?.subject.trim() ||
            task.suggested_title?.trim() ||
            task.source_file_name,
          assetId: result.resultAssetIds?.[task.id],
          indexStatus: result.resultIndexStatuses?.[task.id],
        }));
      setCompletedReviewItems((current) => [
        ...current.filter((item) => !succeeded.has(item.taskId)),
        ...completed,
      ]);
      setReviewTasks((current) => current.filter((task) => !succeeded.has(task.id)));
      setDialogError(
        `${result.failedIds.length} 项资料确认未完成，已保留本次核对内容，请根据行内提示修正后重试。`,
      );
    };
    const commonArgs = [
      selectedConfirmTasks,
      destination,
      projectId,
      submittedRows,
      warningCodesByTask,
      true,
      onCompleted,
    ] as const;
    if (destination === "personal") {
      void flow.handleBatchConfirm(
        ...commonArgs,
        Object.keys(aiReviewDrafts).length > 0 ? aiReviewDrafts : undefined,
        personalDirectoryByTask,
      );
    } else if (Object.keys(aiReviewDrafts).length > 0) {
      void flow.handleBatchConfirm(...commonArgs, aiReviewDrafts);
    } else {
      void flow.handleBatchConfirm(...commonArgs);
    }
  };

  const handleDuplicateDecision = async (
    task: PendingIngestItemDTO,
    action: "skip" | "independent" | "keep",
  ) => {
    if (
      duplicateDecisionTaskId ||
      (targetLibrary !== "personal" && targetLibrary !== "project" && targetLibrary !== "company")
    ) {
      return;
    }
    if (
      action === "independent" &&
      !window.confirm("仍作为独立资料入库会创建新的独立资产，且不会覆盖已有资料。是否继续？")
    ) {
      return;
    }
    setDuplicateDecisionTaskId(task.id);
    setDialogError(null);
    try {
      const response = await decideUploadDuplicate({
        taskId: task.id,
        action,
        targetScope: targetLibrary,
        targetProjectId: targetProjectId || undefined,
      });
      if (action === "keep") {
        const knownTasks = new Map(
          [...reviewTasks, ...skippedDuplicateItems.map((item) => item.task)].map((item) => [
            item.id,
            item,
          ]),
        );
        const skippedIds = new Set(response.skipped_task_ids);
        setReviewTasks((current) => [
          ...current.filter((item) => !skippedIds.has(item.id) && item.id !== task.id),
          task,
        ]);
        setSkippedDuplicateItems((current) => {
          const byId = new Map(current.map((item) => [item.task.id, item]));
          byId.delete(task.id);
          response.skipped_task_ids.forEach((taskId) => {
            const skippedTask = knownTasks.get(taskId);
            const existingDuplicate =
              personalDuplicates[taskId] ??
              previews[taskId]?.duplicate ??
              byId.get(taskId)?.duplicate;
            if (skippedTask && existingDuplicate) {
              byId.set(taskId, {
                task: skippedTask,
                duplicate: { ...existingDuplicate, default_selected: false, decision: "skip" },
              });
            }
          });
          return [...byId.values()];
        });
        if (targetLibrary === "personal" && response.duplicate) {
          setPersonalDuplicates((current) => ({ ...current, [task.id]: response.duplicate! }));
        } else if (response.duplicate) {
          setPreviews((current) =>
            current[task.id]
              ? {
                  ...current,
                  [task.id]: { ...current[task.id], duplicate: response.duplicate! },
                }
              : current,
          );
          if (!previews[task.id] && rows[task.id]) scheduleRowPreview(task.id, rows[task.id]);
        }
      } else if (action === "skip") {
        const skippedDuplicate =
          targetLibrary === "personal" ? personalDuplicates[task.id] : previews[task.id]?.duplicate;
        if (skippedDuplicate) {
          setSkippedDuplicateItems((current) =>
            current.some((item) => item.task.id === task.id)
              ? current
              : [...current, { task, duplicate: skippedDuplicate }],
          );
        }
        setReviewTasks((current) => current.filter((item) => item.id !== task.id));
        setPersonalDuplicates((current) => {
          const next = { ...current };
          delete next[task.id];
          return next;
        });
        setPreviews((current) => {
          const next = { ...current };
          delete next[task.id];
          return next;
        });
      } else if (targetLibrary === "personal") {
        const refreshed = await previewIngestNaming(task.id, {
          target_scope: "personal",
          confidentiality_level: task.suggested_confidentiality_level ?? "L2",
        });
        setPersonalDuplicates((current) => ({
          ...current,
          [task.id]: refreshed.duplicate ?? task.duplicate ?? EMPTY_DUPLICATE,
        }));
      } else {
        await refreshPreviews();
      }
    } catch (error) {
      setDialogError(commandErrorMessage(error, "重复处理决定未保存，请刷新后重试"));
    } finally {
      setDuplicateDecisionTaskId(null);
    }
  };

  const closeAndResetReview = () => {
    cancelPendingPreviews();
    targetOptions.reset();
    aiReview.reset();
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
    setBulkDirectoryKey("");
    setBulkPersonalDirectoryKey("");
    setPersonalDirectoryByTask({});
    setFallbackDirectoryTaskId(null);
    setFallbackDirectoryKey("");
    setDialogError(null);
    setReviewTasks([]);
    setReviewInitialCount(0);
    setCompletedReviewItems([]);
    setPersonalDuplicates({});
    setDuplicateDecisionTaskId(null);
    setSkippedDuplicateItems([]);
  };

  const requestCloseReview = () => {
    const previewInProgress = Object.values(previewBusyByTask).some(Boolean);
    if (editedTaskIds.size > 0 || previewInProgress || confirmingTaskId) {
      setCloseGuardOpen(true);
      return;
    }
    closeAndResetReview();
  };

  return {
    advanceTarget,
    aiReview,
    aiReviewDrafts,
    allPreviewed,
    bulkDirectoryKey,
    bulkPersonalDirectoryKey,
    cancelPendingPreviews,
    closeAndResetReview,
    closeGuardOpen,
    company,
    completedReviewItems,
    confirmCandidate,
    confirmOpen,
    confirmSingle,
    confirmSingleDelete,
    confirmingTaskId,
    deleteCandidate,
    deleteFeedback,
    deletingTaskId,
    duplicateDecisionTaskId,
    skippedDuplicateItems,
    dialogError,
    directoryLabel,
    editedTaskIds,
    fallbackDirectoryKey,
    fallbackDirectoryTaskId,
    filterSnapshot,
    formalDirectories,
    liveSelectedConfirmTasks,
    loadAiReview,
    loading,
    missingDates,
    options,
    personalDirectoryByTask,
    personalDuplicates,
    previewBusyByTask,
    previewFeedback,
    previewRunsRef,
    previewSummary,
    previewTimersRef,
    previews,
    refreshPreviews,
    rejectOpen,
    requestCloseReview,
    handleDuplicateDecision,
    resetTargetReviewContext,
    reviewFilter,
    reviewInitialCount,
    reviewTargetKey,
    reviewTasks,
    reviewedTaskIds,
    rows,
    saveAiReviewDraft,
    scheduleRowPreview,
    selectedConfirmTasks,
    selectedRejectTasks,
    setBulkDirectoryKey,
    setBulkPersonalDirectoryKey,
    setCloseGuardOpen,
    setCompletedReviewItems,
    setConfirmCandidate,
    setConfirmOpen,
    setConfirmingTaskId,
    setDeleteCandidate,
    setDeleteFeedback,
    setDeletingTaskId,
    setDialogError,
    setEditedTaskIds,
    setFallbackDirectoryKey,
    setFallbackDirectoryTaskId,
    setFilterSnapshot,
    setLoading,
    setOptions,
    setPersonalDirectoryByTask,
    setPreviewBusyByTask,
    setPreviewFeedback,
    setPreviews,
    setRejectOpen,
    setReviewFilter,
    setReviewInitialCount,
    setReviewTargetKey,
    setReviewTasks,
    setReviewedTaskIds,
    setRows,
    setStage,
    setTargetLibrary,
    setTargetProjectId,
    stage,
    stateCounts,
    statesByTask,
    submitBatchReview,
    targetKey,
    targetLibrary,
    targetOptions,
    targetOptionsBusy,
    targetOptionsError,
    targetProjectId,
    targetReady,
    updateRow,
    visibleConfirmTasks,
    visibleTaskIds,
    warningCodesByTask,
    warningNotices,
  };
}
