import ConfirmDialog from "../../components/ConfirmDialog";
import NamingReviewWorkspace from "../../components/NamingReviewWorkspace";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type { UploadFlow } from "./useUploadFlow";
import PendingBatchActionBar from "./PendingBatchActionBar";
import PendingBatchAiReviewDrawer from "./PendingBatchAiReviewDrawer";
import PendingBatchDecisionDialogs from "./PendingBatchDecisionDialogs";
import PendingBatchNamingReview from "./PendingBatchNamingReview";
import { PendingBatchPersonalReview, PendingBatchTargetStep } from "./PendingBatchTargetReview";
import { usePendingBatchReviewController } from "./usePendingBatchReviewController";

export default function PendingBatchActions({
  tasks,
  flow,
}: {
  tasks: PendingIngestItemDTO[];
  flow: UploadFlow;
}) {
  const {
    advanceTarget,
    aiReview,
    allPreviewed,
    bulkCategoryId,
    bulkCategoryTaskIds,
    bulkPersonalDirectoryKey,
    categories,
    categorySuggestions,
    categoryTargetLabel,
    classificationBusy,
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
    dialogError,
    directoryLabel,
    editedTaskIds,
    fallbackDirectoryKey,
    fallbackDirectoryTaskId,
    formalDirectories,
    liveSelectedConfirmTasks,
    loadAiReview,
    loading,
    options,
    personalDirectoryByTask,
    previewBusyByTask,
    previewFeedback,
    previewSummary,
    previews,
    refreshPreviews,
    rejectOpen,
    requestCloseReview,
    resetTargetReviewContext,
    retryCategoryClassifications,
    retryOneCategoryClassification,
    reviewFilter,
    reviewInitialCount,
    rows,
    saveAiReviewDraft,
    scheduleRowPreview,
    selectManualCategory,
    selectedConfirmTasks,
    selectedRejectTasks,
    setBulkCategoryId,
    setBulkPersonalDirectoryKey,
    setCloseGuardOpen,
    setCompletedReviewItems,
    setConfirmCandidate,
    setConfirmOpen,
    setDeleteCandidate,
    setDeleteFeedback,
    setDialogError,
    setFallbackDirectoryKey,
    setFallbackDirectoryTaskId,
    setFilterSnapshot,
    setPersonalDirectoryByTask,
    setRejectOpen,
    setReviewFilter,
    setReviewInitialCount,
    setReviewTasks,
    setStage,
    setTargetLibrary,
    setTargetProjectId,
    stage,
    stateCounts,
    statesByTask,
    submitBatchReview,
    targetLibrary,
    targetOptions,
    targetOptionsBusy,
    targetOptionsError,
    targetProjectId,
    targetReady,
    updateRow,
    visibleConfirmTasks,
    warningNotices,
  } = usePendingBatchReviewController(tasks, flow);

  if (
    !confirmOpen &&
    !rejectOpen &&
    liveSelectedConfirmTasks.length === 0 &&
    selectedRejectTasks.length === 0
  ) {
    return null;
  }

  const GovernedConfirmSurface = stage === "review" ? NamingReviewWorkspace : ConfirmDialog;

  return (
    <>
      <PendingBatchActionBar
        busy={flow.batchBusy}
        confirmCount={selectedConfirmTasks.length}
        operation={flow.batchOperation}
        rejectCount={selectedRejectTasks.length}
        onConfirm={() => {
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
        onReject={() => setRejectOpen(true)}
      />

      <GovernedConfirmSurface
        open={confirmOpen}
        title={
          stage === "target"
            ? `确认入库 ${selectedConfirmTasks.length} 项资料`
            : targetLibrary === "personal"
              ? `核对 ${reviewInitialCount} 项个人入库`
              : `逐条核对 ${reviewInitialCount} 项规范命名`
        }
        description={
          stage === "target"
            ? "请选择一个明确的目标知识库；取消不会创建资产或改变任务状态。"
            : undefined
        }
        confirmText={
          stage === "target" && dialogError && targetLibrary !== "personal"
            ? "重新加载规则"
            : stage === "review" || !targetLibrary
              ? warningNotices.length > 0
                ? `仍然确认已选择的 ${selectedConfirmTasks.length} 项入库`
                : `确认已选择的 ${selectedConfirmTasks.length} 项入库`
              : targetLibrary === "personal"
                ? "下一步：核对入库"
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
        panelClassName={
          stage === "review"
            ? targetLibrary === "personal"
              ? "upload77-personal-directory-dialog"
              : "upload77-batch-naming-dialog"
            : undefined
        }
        closeButtonLabel={
          stage === "review"
            ? targetLibrary === "personal"
              ? "关闭个人入库核对"
              : "关闭批量命名核对"
            : undefined
        }
        onCancel={requestCloseReview}
        onConfirm={stage === "target" ? () => void advanceTarget() : submitBatchReview}
      >
        {stage === "target" ? (
          <PendingBatchTargetStep
            flow={flow}
            targetLibrary={targetLibrary}
            targetProjectId={targetProjectId}
            targetOptionsBusy={targetOptionsBusy}
            targetOptionsError={targetOptionsError}
            bulkPersonalDirectoryKey={bulkPersonalDirectoryKey}
            bulkCategoryId={bulkCategoryId}
            formalDirectories={formalDirectories}
            options={options}
            onResetReview={resetTargetReviewContext}
            onLibraryChange={(value) => {
              setTargetLibrary(value);
              setTargetProjectId("");
              setDialogError(null);
            }}
            onProjectChange={(value) => {
              setTargetProjectId(value);
              setDialogError(null);
            }}
            onPersonalDirectoryChange={(value) => {
              setBulkPersonalDirectoryKey(value);
              setDialogError(null);
            }}
            onCategoryChange={setBulkCategoryId}
            onRetryOptions={targetOptions.retry}
          />
        ) : targetLibrary === "personal" ? (
          <PendingBatchPersonalReview
            tasks={selectedConfirmTasks}
            directoryLabel={directoryLabel(bulkPersonalDirectoryKey)}
            formalDirectories={formalDirectories}
            directoryByTask={personalDirectoryByTask}
            setDirectoryByTask={setPersonalDirectoryByTask}
            batchErrors={flow.batchErrors}
            onOpenAi={loadAiReview}
          />
        ) : (
          <PendingBatchNamingReview
            previewSummary={previewSummary}
            visibleConfirmTasks={visibleConfirmTasks}
            selectedConfirmTasks={selectedConfirmTasks}
            categoryTargetLabel={categoryTargetLabel}
            bulkCategoryId={bulkCategoryId}
            loading={loading}
            classificationBusy={classificationBusy}
            retryCategoryClassifications={retryCategoryClassifications}
            refreshPreviews={refreshPreviews}
            reviewFilter={reviewFilter}
            setReviewFilter={setReviewFilter}
            setFilterSnapshot={setFilterSnapshot}
            statesByTask={statesByTask}
            stateCounts={stateCounts}
            completedReviewItems={completedReviewItems}
            warningNotices={warningNotices}
            rows={rows}
            previews={previews}
            editedTaskIds={editedTaskIds}
            loadAiReview={loadAiReview}
            flow={flow}
            deletingTaskId={deletingTaskId}
            confirmingTaskId={confirmingTaskId}
            setConfirmCandidate={setConfirmCandidate}
            setDeleteCandidate={setDeleteCandidate}
            deleteFeedback={deleteFeedback}
            setDeleteFeedback={setDeleteFeedback}
            categories={categories}
            categorySuggestions={categorySuggestions}
            bulkCategoryTaskIds={bulkCategoryTaskIds}
            directoryLabel={directoryLabel}
            retryOneCategoryClassification={retryOneCategoryClassification}
            updateRow={updateRow}
            selectManualCategory={selectManualCategory}
            company={company}
            options={options}
            previewBusyByTask={previewBusyByTask}
            previewFeedback={previewFeedback}
            scheduleRowPreview={scheduleRowPreview}
            targetLibrary={targetLibrary}
            setFallbackDirectoryTaskId={setFallbackDirectoryTaskId}
            setFallbackDirectoryKey={setFallbackDirectoryKey}
          />
        )}
      </GovernedConfirmSurface>

      <PendingBatchAiReviewDrawer review={aiReview} onSave={saveAiReviewDraft} />
      <PendingBatchDecisionDialogs
        fallbackDirectoryTaskId={fallbackDirectoryTaskId}
        fallbackDirectoryKey={fallbackDirectoryKey}
        formalDirectories={formalDirectories}
        targetLibrary={targetLibrary}
        onFallbackKeyChange={setFallbackDirectoryKey}
        onCancelFallback={() => {
          setFallbackDirectoryTaskId(null);
          setFallbackDirectoryKey("");
        }}
        onSaveFallback={updateRow}
        closeGuardOpen={closeGuardOpen}
        onCancelCloseGuard={() => setCloseGuardOpen(false)}
        onConfirmCloseGuard={closeAndResetReview}
        confirmCandidate={confirmCandidate}
        previews={previews}
        confirmingTaskId={confirmingTaskId}
        onCancelConfirm={() => setConfirmCandidate(null)}
        onConfirmOne={() => void confirmSingle()}
        deleteCandidate={deleteCandidate}
        deletingTaskId={deletingTaskId}
        onCancelDelete={() => setDeleteCandidate(null)}
        onConfirmDelete={() => void confirmSingleDelete()}
        rejectOpen={rejectOpen}
        selectedRejectTasks={selectedRejectTasks}
        flow={flow}
        onCancelReject={() => setRejectOpen(false)}
      />
    </>
  );
}
