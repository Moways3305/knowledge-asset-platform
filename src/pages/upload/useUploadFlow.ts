import { useState, useCallback } from "react";
import { ControlledBulkRequestError } from "../../api/bulk";
import { ApiError } from "../../api/http";
import { bulkConfirmIngest, deletePendingTask } from "../../api/ingest";
import type { IngestConfirmRequestDTO, PendingIngestItemDTO } from "../../types/ingest";
import type { BatchNamingValuesDTO } from "../../types/naming";
import { useModelSelection } from "../../hooks/useModelSelection";
import { type PathBranch, type TargetLibrary } from "./uploadConstants";
import { useIngestConfirmation } from "./useIngestConfirmation";
import { useUploadIntake } from "./useUploadIntake";
import { usePendingIngest } from "./usePendingIngest";

function classifyPermanentRejectError(error: unknown): { message: string; retryable: boolean } {
  if (!(error instanceof ApiError)) {
    return { message: "网络连接中断，任务仍保留，可重试。", retryable: true };
  }
  if (error.status >= 500 || error.deniedReason === "ingest_delete_temporarily_unavailable") {
    return {
      message:
        error.deniedReason === "ingest_delete_temporarily_unavailable"
          ? "审核关联清理暂时不可用，任务仍保留，可重试。"
          : "服务暂时不可用，任务仍保留，可重试。",
      retryable: true,
    };
  }
  if (error.status === 403) {
    return { message: "无权限：仅创建人可永久删除该任务。", retryable: false };
  }
  if (error.status === 404) {
    return { message: "任务已删除或不存在，请刷新列表。", retryable: false };
  }
  if (error.deniedReason === "ingest_already_confirmed") {
    return { message: "已入库：该任务已形成知识资产，不能永久删除。", retryable: false };
  }
  if (error.deniedReason === "ingest_review_cleanup_conflict") {
    return { message: "审核关联状态异常，无法安全删除，请刷新后联系管理员。", retryable: false };
  }
  if (error.status === 409) {
    return { message: "状态已变化：当前任务不能永久删除，请刷新列表。", retryable: false };
  }
  return { message: "请求无法执行，任务仍保留，请刷新列表。", retryable: false };
}

type BatchReviewDeleteResult = { ok: true } | { ok: false; message: string; retryable: boolean };
type BatchConfirmResult = {
  succeededIds: string[];
  failedIds: string[];
  resultAssetIds?: Record<string, string>;
};

export type {
  LocalUploadQueueItem,
  LocalUploadQueueState,
  UploadIntakeFeedback,
} from "./uploadIntake";

// 资产化确认工作台的容器 Hook：收拢企业微信待确认 / 本地上传共享的
// 全部状态、AI 结果轮询、人工校正字段、确认入库与重置逻辑。页面本体只消费此 hook、
// 做步骤路由与顶层 state 传递；展示拆到 UploadStepA / UploadStepB / UploadConfirmPanel。
export function useUploadFlow() {
  const [activePath, setActivePath] = useState<PathBranch>("b");

  // PBC-38：入库模型选择（默认平台推荐 embedding/rerank；缺默认时禁用提交）。
  const models = useModelSelection();

  const pending = usePendingIngest(activePath);
  const {
    pendingTasks,
    setPendingTasks,
    pendingLoading,
    setPendingLoading,
    pendingError,
    localPendingTasks,
    setLocalPendingTasks,
    localPendingLoading,
    setLocalPendingLoading,
    localPendingError,
    loadPending,
    loadLocalPending,
    batchSelection,
    setBatchSelection,
    batchStatus,
    setBatchStatus,
    batchBusy,
    setBatchBusy,
    batchOperation,
    setBatchOperation,
    batchErrors,
    setBatchErrors,
    batchRejectRetryability,
    setBatchRejectRetryability,
    batchRunRef,
    pendingRequestRef,
    localPendingRequestRef,
    toggleBatchTask,
    setBatchTasksSelected,
    cancelBatchRun,
  } = pending;
  const intake = useUploadIntake({
    activePath,
    loadLocalPending,
    setLocalPendingTasks,
  });
  const {
    localUploadQueue,
    uploadSession,
    folderDropNotice,
    intakeFeedback,
    fileRef,
    folderRef,
    retryLocalUpload,
    removeLocalUpload,
    removeFailedLocalUploads,
    handleFileSelect,
    handleFolderSelect,
    handleFileDrop,
    handleDataTransferDrop,
    removeLocalTaskEverywhere,
    cancelIntakeRuns,
  } = intake;

  const confirmation = useIngestConfirmation({
    activePath,
    embeddingModelRef: models.embeddingRef,
    rerankModelRef: models.rerankRef,
    loadPending,
    loadLocalPending,
    removeLocalTask: removeLocalTaskEverywhere,
    beforeSingleTask: cancelBatchRun,
  });
  const {
    flowState,
    fileName,
    fileSize,
    fileType,
    selectedTaskName,
    taskId,
    resultAssetId,
    submitReviewId,
    submitIndexStatus,
    apiError,
    setApiError,
    processingNote,
    editTitle,
    setEditTitle,
    editOneLiner,
    setEditOneLiner,
    editSummary,
    setEditSummary,
    editKeyPoints,
    setEditKeyPoints,
    editTags,
    setEditTags,
    editConfidentiality,
    setEditConfidentiality,
    targetLibrary,
    setTargetLibrary,
    targetLocked,
    targetProjectId,
    setTargetProjectId,
    canUseCompanyTarget,
    projects,
    llmStatus,
    desensitization,
    suggestionGeneration,
    generationErrorCategory,
    regenerating,
    regenerationError,
    handleRegenerateSuggestions,
    extraction,
    naming,
    namingOptions,
    namingCategoryId,
    setNamingCategoryId,
    namingFormedOn,
    setNamingFormedOn,
    namingVersion,
    setNamingVersion,
    namingApplicableTo,
    setNamingApplicableTo,
    namingPreview,
    namingPreviewBusy,
    namingPreviewError,
    namingPreviewReady,
    namingRequired,
    pollAiResult,
    handleSelectPendingTask,
    handleStart,
    handleRefreshProcessing,
    handleSubmit,
    resetConfirmation,
    beginWorkflowRun,
    isCurrentWorkflowRun,
  } = confirmation;

  // The queue is intentionally awaited one item at a time. One explicit
  // destination applies to the whole batch; persisted source locks are checked
  // both here for feedback and by the server as the authority.
  const handleBatchConfirm = useCallback(
    async (
      tasks: PendingIngestItemDTO[],
      destination: Exclude<TargetLibrary, "">,
      destinationProjectId?: string,
      namingByTask?: Record<string, BatchNamingValuesDTO>,
      warningCodesByTask?: Record<string, string[]>,
      preserveUnsubmittedSelection = false,
      onCompleted?: (result: BatchConfirmResult) => void,
    ): Promise<void> => {
      if (batchRunRef.current !== null || tasks.length === 0) {
        return;
      }
      if (destination === "project" && !destinationProjectId) {
        return;
      }
      const runId = beginWorkflowRun();
      const isCurrent = () => batchRunRef.current === runId && isCurrentWorkflowRun(runId);
      const updateBatchStatus = (
        update: (
          previous: Record<string, "waiting" | "processing" | "success" | "failed">,
        ) => Record<string, "waiting" | "processing" | "success" | "failed">,
      ) => {
        if (!isCurrent()) return;
        setBatchStatus(update);
      };
      batchRunRef.current = runId;
      setBatchBusy(true);
      setBatchOperation("confirm");
      setBatchErrors((previous) => {
        const next = { ...previous };
        tasks.forEach((task) => delete next[task.id]);
        return next;
      });
      setBatchRejectRetryability((previous) => {
        const next = { ...previous };
        tasks.forEach((task) => delete next[task.id]);
        return next;
      });
      let completed = false;
      let preserveRetry = false;
      let retrySelection: string[] = [];
      const succeededIds = new Set<string>();
      const resultAssetIds: Record<string, string> = {};
      const prepared: Array<{
        task: PendingIngestItemDTO;
        confirmation: IngestConfirmRequestDTO;
      }> = [];
      updateBatchStatus((previous) => {
        const next = { ...previous };
        tasks.forEach((task) => {
          next[task.id] = "waiting";
        });
        return next;
      });
      try {
        for (const task of tasks) {
          if (!isCurrent()) return;
          updateBatchStatus((previous) => ({ ...previous, [task.id]: "processing" }));
          try {
            const ai = await pollAiResult(task.id, isCurrent);
            if (!isCurrent()) return;
            if (!ai || ai.status === "processing" || ai.status === "failed") {
              throw new Error("该资料尚未准备好确认入库");
            }
            if (task.target_scope && task.target_scope !== destination) {
              throw new Error("该资料目标已由来源规则锁定");
            }
            if (
              destination === "project" &&
              task.target_project_id &&
              task.target_project_id !== destinationProjectId
            ) {
              throw new Error("该资料目标项目已由来源规则锁定");
            }
            const governedNaming = namingByTask?.[task.id];
            const title =
              governedNaming?.subject.trim() ||
              ai.suggested_title?.trim() ||
              task.suggested_title?.trim() ||
              "";
            const summary = ai.suggested_summary?.trim() || ai.suggested_one_liner?.trim() || "";
            if (!title || !summary) throw new Error("该资料缺少可确认的标题或摘要");
            if (!isCurrent()) return;
            prepared.push({
              task,
              confirmation: {
                title,
                one_liner: ai.suggested_one_liner || undefined,
                summary,
                key_points: ai.suggested_key_points?.filter(Boolean) || [],
                tags: ai.suggested_tags?.filter(Boolean) || [],
                target_scope: destination,
                target_project_id: destination === "project" ? destinationProjectId : undefined,
                target_zone: "material",
                confidentiality_level:
                  governedNaming?.confidentiality_level ||
                  ai.suggested_confidentiality_level ||
                  "L2",
                embedding_model_ref: models.embeddingRef || undefined,
                rerank_model_ref: models.rerankRef || undefined,
                acknowledged_naming_warning_codes: warningCodesByTask?.[task.id] ?? [],
                naming: governedNaming
                  ? {
                      category_id: governedNaming.category_id,
                      subject: governedNaming.subject,
                      formed_on: governedNaming.formed_on,
                      version: governedNaming.version,
                      applicable_to:
                        destination === "company" ? governedNaming.applicable_to : undefined,
                    }
                  : undefined,
              },
            });
            updateBatchStatus((previous) => ({ ...previous, [task.id]: "waiting" }));
          } catch (error) {
            if (!isCurrent()) return;
            // One failure is shown on that row and never prevents the next task.
            updateBatchStatus((previous) => ({ ...previous, [task.id]: "failed" }));
            setBatchErrors((previous) => ({
              ...previous,
              [task.id]: error instanceof Error ? error.message : "资料尚未准备好",
            }));
          }
        }
        if (prepared.length > 0) {
          prepared.forEach(({ task }) =>
            updateBatchStatus((previous) => ({ ...previous, [task.id]: "processing" })),
          );
          const response = await bulkConfirmIngest({
            items: prepared.map(({ task, confirmation }) => ({
              taskId: task.id,
              confirmation,
            })),
            targetScope: destination,
            targetProjectId: destinationProjectId,
          });
          if (!isCurrent()) return;
          const retryableFailedIds: string[] = [];
          response.items.forEach((item) => {
            const succeeded = item.status === "succeeded";
            updateBatchStatus((previous) => ({
              ...previous,
              [item.item_id]: succeeded ? "success" : "failed",
            }));
            if (succeeded) succeededIds.add(item.item_id);
            if (succeeded && item.result_asset_id) {
              resultAssetIds[item.item_id] = item.result_asset_id;
            }
            if (succeeded && activePath === "b") removeLocalTaskEverywhere(item.item_id);
            if (!succeeded) {
              if (
                item.status === "failed" ||
                item.reason_code?.startsWith("naming_") ||
                item.reason_code === "canonical_name_too_long"
              ) {
                retryableFailedIds.push(item.item_id);
              }
              setBatchErrors((previous) => ({
                ...previous,
                [item.item_id]: item.message ?? "当前状态或权限已变化",
              }));
            }
          });
          retrySelection = retryableFailedIds;
        }
        if (!isCurrent()) return;
        completed = true;
        const refreshRequestRef = activePath === "a" ? pendingRequestRef : localPendingRequestRef;
        const expectedRefreshRequest = refreshRequestRef.current + 1;
        if (activePath === "a") await loadPending();
        else await loadLocalPending();
        if (isCurrent() && refreshRequestRef.current === expectedRefreshRequest) {
          setBatchSelection((current) =>
            preserveUnsubmittedSelection
              ? current.filter((id) => !succeededIds.has(id))
              : retrySelection,
          );
        }
      } catch (error) {
        if (!isCurrent()) return;
        const partial = error instanceof ControlledBulkRequestError ? error.partialResult : null;
        const retryIds = new Set(
          error instanceof ControlledBulkRequestError
            ? error.retryItems.map((item) => item.taskId)
            : prepared.map(({ task }) => task.id),
        );
        partial?.items.forEach((item) => {
          const succeeded = item.status === "succeeded";
          updateBatchStatus((previous) => ({
            ...previous,
            [item.item_id]: succeeded ? "success" : "failed",
          }));
          if (succeeded) succeededIds.add(item.item_id);
          const resultAssetId = (item as { result_asset_id?: unknown }).result_asset_id;
          if (succeeded && typeof resultAssetId === "string") {
            resultAssetIds[item.item_id] = resultAssetId;
          }
          if (succeeded && activePath === "b") removeLocalTaskEverywhere(item.item_id);
          if (item.status === "failed") retryIds.add(item.item_id);
        });
        retryIds.forEach((itemId) => {
          updateBatchStatus((previous) => ({ ...previous, [itemId]: "failed" }));
          setBatchErrors((previous) => ({
            ...previous,
            [itemId]: "提交中断，该资料仍可重试。",
          }));
        });
        retrySelection = [...retryIds];
        preserveRetry = true;
        const refreshRequestRef = activePath === "a" ? pendingRequestRef : localPendingRequestRef;
        const expectedRefreshRequest = refreshRequestRef.current + 1;
        if (activePath === "a") await loadPending();
        else await loadLocalPending();
        if (isCurrent() && refreshRequestRef.current === expectedRefreshRequest) {
          setBatchSelection((current) =>
            preserveUnsubmittedSelection
              ? current.filter((id) => !succeededIds.has(id))
              : retrySelection,
          );
        }
      } finally {
        // A single-task selection can invalidate this run without going through
        // handleReset. Release only this batch's lock, never a newer batch's.
        if (batchRunRef.current === runId) {
          batchRunRef.current = null;
          setBatchBusy(false);
          setBatchOperation(null);
          if (!completed && !preserveRetry) {
            setBatchSelection([]);
            setBatchStatus({});
          }
        }
      }
      onCompleted?.({
        succeededIds: [...succeededIds],
        failedIds: tasks.map((task) => task.id).filter((id) => !succeededIds.has(id)),
        resultAssetIds,
      });
    },
    [
      activePath,
      batchRunRef,
      beginWorkflowRun,
      isCurrentWorkflowRun,
      localPendingRequestRef,
      loadLocalPending,
      loadPending,
      models.embeddingRef,
      models.rerankRef,
      pendingRequestRef,
      pollAiResult,
      removeLocalTaskEverywhere,
      setBatchBusy,
      setBatchErrors,
      setBatchRejectRetryability,
      setBatchOperation,
      setBatchSelection,
      setBatchStatus,
    ],
  );

  const handleSingleBatchConfirm = useCallback(
    async (
      task: PendingIngestItemDTO,
      destination: "project" | "company",
      destinationProjectId: string | undefined,
      naming: BatchNamingValuesDTO,
      warningCodes: string[] = [],
    ): Promise<BatchConfirmResult> => {
      let result: BatchConfirmResult = {
        succeededIds: [],
        failedIds: [task.id],
        resultAssetIds: {},
      };
      await handleBatchConfirm(
        [task],
        destination,
        destinationProjectId,
        { [task.id]: naming },
        { [task.id]: warningCodes },
        true,
        (completed) => {
          result = completed;
        },
      );
      return result;
    },
    [handleBatchConfirm],
  );

  // Permanent rejection intentionally reuses the existing one-item DELETE endpoint.
  // Awaiting each request preserves per-item authorization/audit and prevents parallel deletion.
  const handleBatchReject = useCallback(
    async (tasks: PendingIngestItemDTO[]) => {
      if (batchRunRef.current !== null || tasks.length === 0) return;
      const sourceAtStart = activePath;
      const runId = beginWorkflowRun();
      const isCurrent = () =>
        batchRunRef.current === runId &&
        isCurrentWorkflowRun(runId) &&
        activePath === sourceAtStart;
      batchRunRef.current = runId;
      setBatchBusy(true);
      setBatchOperation("reject");
      setBatchErrors((previous) => {
        const next = { ...previous };
        tasks.forEach((task) => delete next[task.id]);
        return next;
      });
      setBatchRejectRetryability((previous) => {
        const next = { ...previous };
        tasks.forEach((task) => delete next[task.id]);
        return next;
      });
      setBatchStatus((previous) => {
        const next = { ...previous };
        tasks.forEach((task) => {
          next[task.id] = "waiting";
        });
        return next;
      });

      const failed = new Set<string>();
      let completed = false;
      try {
        for (const task of tasks) {
          if (!isCurrent()) return;
          setBatchStatus((previous) => ({ ...previous, [task.id]: "processing" }));
          try {
            await deletePendingTask(task.id);
            if (!isCurrent()) return;
            setBatchStatus((previous) => ({ ...previous, [task.id]: "success" }));
            const removeTask = (items: PendingIngestItemDTO[]) =>
              items.filter((item) => item.id !== task.id);
            if (sourceAtStart === "a") {
              setPendingTasks(removeTask);
            } else {
              removeLocalTaskEverywhere(task.id);
            }
            setBatchSelection((selected) => selected.filter((id) => id !== task.id));
          } catch (error) {
            if (!isCurrent()) return;
            const classified = classifyPermanentRejectError(error);
            if (classified.retryable) failed.add(task.id);
            setBatchStatus((previous) => ({ ...previous, [task.id]: "failed" }));
            setBatchErrors((previous) => ({
              ...previous,
              [task.id]: classified.message,
            }));
            setBatchRejectRetryability((previous) => ({
              ...previous,
              [task.id]: classified.retryable,
            }));
          }
        }
        if (!isCurrent()) return;
        completed = true;
        if (sourceAtStart === "a") {
          await loadPending();
        } else {
          await loadLocalPending();
        }
        if (isCurrent()) setBatchSelection([...failed]);
      } finally {
        if (batchRunRef.current === runId) {
          batchRunRef.current = null;
          setBatchBusy(false);
          setBatchOperation(null);
          if (!completed) {
            setBatchSelection([]);
            setBatchStatus({});
            setBatchErrors({});
            setBatchRejectRetryability({});
          }
        }
      }
    },
    [
      activePath,
      batchRunRef,
      beginWorkflowRun,
      isCurrentWorkflowRun,
      loadLocalPending,
      loadPending,
      removeLocalTaskEverywhere,
      setBatchBusy,
      setBatchErrors,
      setBatchRejectRetryability,
      setBatchOperation,
      setBatchSelection,
      setBatchStatus,
      setPendingTasks,
    ],
  );

  const handleDeleteBatchReviewItem = useCallback(
    async (taskId: string): Promise<BatchReviewDeleteResult> => {
      if (batchRunRef.current !== null) {
        return { ok: false, message: "当前批量操作尚未结束，请稍后再试。", retryable: true };
      }
      const sourceAtStart = activePath;
      const runId = beginWorkflowRun();
      const isCurrent = () =>
        batchRunRef.current === runId &&
        isCurrentWorkflowRun(runId) &&
        activePath === sourceAtStart;
      batchRunRef.current = runId;
      setBatchBusy(true);
      setBatchOperation("delete");
      try {
        await deletePendingTask(taskId);
        if (!isCurrent()) {
          return {
            ok: false,
            message: "页面状态已变化，请刷新待确认列表。",
            retryable: false,
          };
        }
        const removeTask = (items: PendingIngestItemDTO[]) =>
          items.filter((item) => item.id !== taskId);
        if (sourceAtStart === "a") setPendingTasks(removeTask);
        else removeLocalTaskEverywhere(taskId);
        setBatchSelection((selected) => selected.filter((id) => id !== taskId));
        setBatchStatus((current) => {
          const next = { ...current };
          delete next[taskId];
          return next;
        });
        setBatchErrors((current) => {
          const next = { ...current };
          delete next[taskId];
          return next;
        });
        setBatchRejectRetryability((current) => {
          const next = { ...current };
          delete next[taskId];
          return next;
        });
        return { ok: true };
      } catch (error) {
        if (!isCurrent()) {
          return {
            ok: false,
            message: "页面状态已变化，请刷新待确认列表。",
            retryable: false,
          };
        }
        return { ok: false, ...classifyPermanentRejectError(error) };
      } finally {
        if (batchRunRef.current === runId) {
          batchRunRef.current = null;
          setBatchBusy(false);
          setBatchOperation(null);
        }
      }
    },
    [
      activePath,
      batchRunRef,
      beginWorkflowRun,
      isCurrentWorkflowRun,
      removeLocalTaskEverywhere,
      setBatchBusy,
      setBatchErrors,
      setBatchOperation,
      setBatchRejectRetryability,
      setBatchSelection,
      setBatchStatus,
      setPendingTasks,
    ],
  );

  const handleReset = useCallback(() => {
    resetConfirmation();
    cancelIntakeRuns();
    batchRunRef.current = null;
    setBatchBusy(false);
    setBatchOperation(null);
    setBatchStatus({});
    setBatchErrors({});
    setBatchRejectRetryability({});
    pendingRequestRef.current += 1;
    localPendingRequestRef.current += 1;
    setPendingLoading(false);
    setLocalPendingLoading(false);
    setBatchSelection([]);
  }, [
    batchRunRef,
    cancelIntakeRuns,
    localPendingRequestRef,
    pendingRequestRef,
    resetConfirmation,
    setBatchBusy,
    setBatchErrors,
    setBatchRejectRetryability,
    setBatchOperation,
    setBatchSelection,
    setBatchStatus,
    setLocalPendingLoading,
    setPendingLoading,
  ]);

  // 删除待确认入库任务并清理 UI 状态，完成后刷新列表。
  const handleDeletePending = useCallback(
    async (tid: string) => {
      // Rejecting an ingest item is irreversible. Await it before resetting so
      // a failed delete leaves the current editor and source context available.
      const sourceAtStart = activePath;
      const runId = beginWorkflowRun();
      const isCurrent = () => isCurrentWorkflowRun(runId);
      setApiError(null);
      try {
        await deletePendingTask(tid);
        if (!isCurrent()) return;
        if (sourceAtStart === "b") removeLocalTaskEverywhere(tid);
        handleReset();
        // Refresh only the active source. The two lists have independent request
        // tokens, so a local action cannot leave the WeCom list loading (or vice versa).
        if (sourceAtStart === "a") void loadPending();
        else void loadLocalPending();
      } catch {
        if (!isCurrent()) return;
        setApiError("拒绝入库失败，任务仍保留，请重试");
      }
    },
    [
      activePath,
      beginWorkflowRun,
      handleReset,
      isCurrentWorkflowRun,
      loadPending,
      loadLocalPending,
      removeLocalTaskEverywhere,
      setApiError,
    ],
  );

  // 切换来源时清空当前流程 / 选中态，避免一处来源的校正数据残留到另一处。
  const switchPath = useCallback(
    (p: PathBranch) => {
      if (p === activePath) return;
      handleReset();
      // Keep the destination in an honest loading state between the source
      // switch render and the destination effect starting its request.
      if (p === "a") setPendingLoading(true);
      else setLocalPendingLoading(true);
      setActivePath(p);
    },
    [activePath, handleReset, setLocalPendingLoading, setPendingLoading],
  );

  const confirmReady = flowState === "ready";
  const requiredFieldsOk =
    editTitle.trim().length > 0 &&
    (editSummary.trim().length > 0 || editOneLiner.trim().length > 0) &&
    targetLibrary !== "" &&
    (targetLibrary !== "project" || targetProjectId.length > 0);
  // 平台默认嵌入或问答模型未配置时禁用提交（models.blockSubmit），不静默走 .env 兜底。
  const canSubmit = confirmReady && requiredFieldsOk && namingPreviewReady && !models.blockSubmit;
  const confirmSubmitted = flowState === "submitted";
  const awaitingProjectReview = confirmSubmitted && submitReviewId !== null;
  const sourceLabel = activePath === "a" ? "企微微盘" : "本地上传";
  const sourceFile = activePath === "a" ? selectedTaskName : fileName;
  const hasFile = flowState !== "idle";

  return {
    activePath,
    switchPath,
    flowState,
    fileName,
    fileSize,
    fileType,
    hasFile,
    extraction,
    desensitization,
    naming,
    namingOptions,
    namingCategoryId,
    setNamingCategoryId,
    namingFormedOn,
    setNamingFormedOn,
    namingVersion,
    setNamingVersion,
    namingApplicableTo,
    setNamingApplicableTo,
    namingPreview,
    namingPreviewBusy,
    namingPreviewError,
    namingRequired,
    fileRef,
    folderRef,
    handleFileSelect,
    handleFolderSelect,
    handleFileDrop,
    handleDataTransferDrop,
    folderDropNotice,
    intakeFeedback,
    localUploadQueue,
    uploadSession,
    retryLocalUpload,
    removeLocalUpload,
    removeFailedLocalUploads,
    handleStart,
    handleRefreshProcessing,
    handleReset,
    handleDeletePending,
    pendingTasks,
    pendingLoading,
    pendingError,
    loadPending,
    localPendingTasks,
    localPendingLoading,
    localPendingError,
    loadLocalPending,
    handleSelectPendingTask,
    batchSelection,
    batchStatus,
    batchBusy,
    batchOperation,
    batchErrors,
    batchRejectRetryability,
    toggleBatchTask,
    setBatchTasksSelected,
    handleBatchConfirm,
    handleSingleBatchConfirm,
    handleBatchReject,
    handleDeleteBatchReviewItem,
    taskId,
    editTitle,
    setEditTitle,
    editOneLiner,
    setEditOneLiner,
    editSummary,
    setEditSummary,
    editKeyPoints,
    setEditKeyPoints,
    editTags,
    setEditTags,
    editConfidentiality,
    setEditConfidentiality,
    targetLibrary,
    setTargetLibrary,
    targetProjectId,
    setTargetProjectId,
    projects,
    suggestionGeneration,
    targetLocked,
    canUseCompanyTarget,
    llmStatus,
    apiError,
    processingNote,
    generationErrorCategory,
    regenerating,
    regenerationError,
    handleRegenerateSuggestions,
    confirmReady,
    confirmSubmitted,
    canSubmit,
    sourceLabel,
    sourceFile,
    resultAssetId,
    submitReviewId,
    awaitingProjectReview,
    submitIndexStatus,
    handleSubmit,
    models,
  };
}

export type UploadFlow = ReturnType<typeof useUploadFlow>;
