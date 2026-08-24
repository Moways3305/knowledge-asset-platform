import { ChevronDown, FileText, FolderOpen, RefreshCw, UploadCloud, X } from "lucide-react";
import { useState } from "react";
import { retryIngestTask } from "../../api/ingest";
import { ApiError } from "../../api/http";
import { extractionLabel, flowLabel, formatFileSize, pendingStatusLabel } from "./uploadConstants";
import BatchTaskProgress from "./BatchTaskProgress";
import PendingBatchActions from "./PendingBatchActions";
import PendingSelectAll, {
  isPendingTaskActionable,
  pendingSelectionReason,
} from "./PendingSelectAll";
import { formatBeijingTime } from "../../utils/time";
import type { IngestTaskStage } from "../../types/ingest";
import type { UploadFlow } from "./useUploadFlow";

const PROCESSING_STAGE_LABELS: Partial<Record<IngestTaskStage, string>> = {
  upload_saved: "原件已接收",
  text_extraction: "正在提取正文",
  ocr_queued: "OCR 等待中",
  ocr_in_progress: "正在 OCR 识别",
  ocr_failed: "OCR 识别失败",
  canonical_markdown_generation: "正在生成 Markdown",
  content_generation: "正在生成内容建议",
  waiting_generation_config: "等待内容生成模型配置",
  content_generation_failed: "内容生成失败",
};

export default function UploadStepB({ flow }: { flow: UploadFlow }) {
  const {
    flowState,
    fileName,
    fileSize,
    fileType,
    hasFile,
    extraction,
    fileRef,
    folderRef,
    handleFileSelect,
    handleFolderSelect,
    handleDataTransferDrop,
    folderDropNotice,
    intakeFeedback,
    handleStart,
    localUploadQueue,
    uploadSession,
    retryLocalUpload,
    removeLocalUpload,
    removeFailedLocalUploads,
    handleRefreshProcessing,
    handleReset,
    handleDeletePending,
    apiError,
    processingNote,
    localPendingTasks,
    localPendingLoading,
    localPendingError,
    loadLocalPending,
    handleSelectPendingTask,
    taskId,
    batchSelection,
    batchStatus,
    batchBusy,
    batchOperation,
    batchErrors,
    batchRejectRetryability = {},
    toggleBatchTask,
    setBatchTasksSelected,
    handleBatchReject,
  } = flow;
  const [isDragging, setIsDragging] = useState(false);
  const [isQueueCollapsed, setIsQueueCollapsed] = useState(false);
  const [isPendingCollapsed, setIsPendingCollapsed] = useState(false);
  const [pendingRetryId, setPendingRetryId] = useState<string | null>(null);
  const [pendingRetryError, setPendingRetryError] = useState<Record<string, string>>({});
  const retryPending = async (id: string) => {
    setPendingRetryId(id);
    setPendingRetryError((current) => ({ ...current, [id]: "" }));
    try {
      await retryIngestTask(id);
      await loadLocalPending();
    } catch (error) {
      setPendingRetryError((current) => ({
        ...current,
        [id]: error instanceof ApiError ? error.message : "重试未发起，请稍后再试。",
      }));
    } finally {
      setPendingRetryId(null);
    }
  };
  const flowMeta = flowLabel(flowState);
  const canRefresh = flowState === "processing" && Boolean(processingNote);
  const hasActiveUploadQueue = localUploadQueue.some((item) =>
    ["queued", "uploading", "processing", "failed"].includes(item.status),
  );
  const uploadQueueCompleted = localUploadQueue.length > 0 && !hasActiveUploadQueue;
  const completedQueueNotice = localUploadQueue.find((item) => item.error)?.error ?? null;
  const extractionStatusText =
    /\.ppt$/i.test(fileName) && extraction?.status === "unsupported"
      ? "当前 .ppt 格式暂不支持自动提取，已保存文件，请人工补全内容"
      : (extractionLabel[extraction?.status ?? ""] ?? "状态待确认");

  return (
    <>
      <div className="upload-input-region upload77-local-workspace">
        <input
          ref={fileRef}
          type="file"
          className="up-file-input"
          accept=".md,.markdown,.txt,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx"
          multiple
          onChange={handleFileSelect}
        />
        <input
          ref={folderRef}
          type="file"
          className="up-file-input"
          // @ts-expect-error webkitdirectory 是非标准属性，Chromium 系浏览器原生支持
          webkitdirectory=""
          multiple
          onChange={handleFolderSelect}
        />

        {!hasFile ? (
          <div
            className="upload-dropzone upload77-dropzone"
            data-dragging={isDragging ? "true" : "false"}
            onDragEnter={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setIsDragging(false);
              }
            }}
            onDragOver={(event) => {
              event.preventDefault();
              setIsDragging(true);
            }}
            onDrop={(event) => {
              event.preventDefault();
              event.stopPropagation();
              setIsDragging(false);
              void handleDataTransferDrop(event.dataTransfer);
            }}
          >
            <UploadCloud size={30} strokeWidth={1.7} aria-hidden="true" />
            <h2>{isDragging ? "松开即可逐项检查" : "拖放文件到这里"}</h2>
            <p className="dropzone-hint">
              支持 Markdown、PDF、Word、PPTX 自动提取及 Excel、纯文本等资料，单文件最大 25 MiB；旧
              .ppt 仅保存，需人工补全
            </p>
            <div className="upload77-dropzone-actions">
              <button
                className="btn-primary"
                onClick={() => fileRef.current?.click()}
                type="button"
              >
                选择文件
              </button>
              <button
                className="btn-primary"
                onClick={() => folderRef.current?.click()}
                type="button"
              >
                <FolderOpen size={15} aria-hidden="true" />
                选择文件夹
              </button>
            </div>
            {folderDropNotice && (
              <div className="upload-inline-info" role="status">
                {folderDropNotice}
              </div>
            )}
          </div>
        ) : (
          <div className="upload77-selected-workspace">
            <div className="up-file-info upload77-file-row">
              <FileText size={22} aria-hidden="true" />
              <div className="up-file-detail">
                <div className="up-file-name">{fileName}</div>
                <div className="up-file-meta">
                  <span>{fileType}</span>
                  <span>{formatFileSize(fileSize)}</span>
                </div>
              </div>
              <div className="up-file-actions">
                {flowState === "file_selected" && (
                  <button className="btn-primary" onClick={handleStart} type="button">
                    开始处理
                  </button>
                )}
                {flowState === "failed" && (
                  <button className="btn-primary" onClick={handleStart} type="button">
                    重新处理
                  </button>
                )}
                {canRefresh && (
                  <button className="btn-secondary" onClick={handleRefreshProcessing} type="button">
                    <RefreshCw size={14} aria-hidden="true" />
                    重新检查
                  </button>
                )}
                <button
                  className="upload77-remove"
                  onClick={() => {
                    if (taskId) void handleDeletePending(taskId);
                    else handleReset();
                  }}
                  type="button"
                >
                  <X size={15} aria-hidden="true" />
                  移除
                </button>
              </div>
            </div>

            <div className={`up-flow-bar upload77-flow ${flowMeta.cls}`} role="status">
              <span className="up-flow-indicator" />
              <span>{flowMeta.text}</span>
              {flowState === "processing" && !processingNote && (
                <span className="up-flow-spinner" />
              )}
            </div>

            {(apiError || processingNote) && (
              <div
                className={`upload-inline-info upload77-process-feedback ${flowState === "failed" || apiError ? "is-error" : ""}`}
                role="alert"
              >
                {apiError || processingNote}
              </div>
            )}

            {extraction && (
              <div className="upload77-extraction">
                <span>内容提取</span>
                <strong>{extractionStatusText}</strong>
                {extraction.charCount != null && extraction.status === "extracted" && (
                  <span>{extraction.charCount} 字</span>
                )}
                {extraction.isDuplicate && <span className="is-warning">检测到可能重复的资料</span>}
              </div>
            )}
          </div>
        )}
      </div>

      {!hasFile && intakeFeedback && (
        <section
          className={`upload77-intake-feedback is-${intakeFeedback.kind}`}
          role={
            intakeFeedback.kind === "network_error" || intakeFeedback.kind === "rejected"
              ? "alert"
              : "status"
          }
          aria-label="本次上传接收结果"
        >
          <div>
            <strong>{intakeFeedback.message}</strong>
            <span>队列逐项状态为最终依据，刷新后仍会从服务端恢复。</span>
          </div>
          <dl>
            <div>
              <dt>检测</dt>
              <dd>{intakeFeedback.total}</dd>
            </div>
            <div>
              <dt>接收</dt>
              <dd>{intakeFeedback.accepted}</dd>
            </div>
            <div>
              <dt>等待批次</dt>
              <dd>{intakeFeedback.waitingBatches}</dd>
            </div>
            <div>
              <dt>拒绝</dt>
              <dd>{intakeFeedback.rejected}</dd>
            </div>
          </dl>
          {intakeFeedback.batchSizes.length > 1 && (
            <p>批次分布：{intakeFeedback.batchSizes.join(" + ")}</p>
          )}
        </section>
      )}

      {!hasFile && uploadQueueCompleted && (
        <section className="upload77-upload-complete" role="status">
          <strong>
            本次上传 {uploadSession?.total_files ?? localUploadQueue.length} 项派生处理已完成
          </strong>
          <span>，规范文本已生成；{localPendingTasks.length} 项待人工确认，尚未进入检索。</span>
          <a href="#local-pending-title">前往待确认入库</a>
          {completedQueueNotice && (
            <span className="upload77-upload-complete-note">{completedQueueNotice}</span>
          )}
        </section>
      )}

      {!hasFile && hasActiveUploadQueue && (
        <section className="upload77-local-queue" aria-labelledby="local-upload-queue-title">
          <div className="upload77-section-head">
            <div>
              <h2 id="local-upload-queue-title">本次上传队列</h2>
              <p>每批最多 200 项连续推进；失败文件不会阻塞后续文件，可单独重试。</p>
            </div>
            <div className="upload77-section-actions">
              {localUploadQueue.some((item) => item.status === "failed") && (
                <button className="btn-secondary" onClick={removeFailedLocalUploads} type="button">
                  清理全部失败项
                </button>
              )}
              <button
                aria-controls="local-upload-queue-body"
                aria-expanded={!isQueueCollapsed}
                className="upload77-icon-button"
                onClick={() => setIsQueueCollapsed((prev) => !prev)}
                title={isQueueCollapsed ? "展开队列" : "折叠队列"}
                type="button"
              >
                <ChevronDown
                  size={15}
                  aria-hidden="true"
                  className={isQueueCollapsed ? "is-collapsed" : ""}
                />
                <span className="upload77-icon-button-label">
                  {isQueueCollapsed ? "展开" : "折叠"}
                </span>
              </button>
            </div>
          </div>
          <div
            id="local-upload-queue-body"
            className={`upload77-section-body ${isQueueCollapsed ? "is-collapsed" : ""}`}
          >
            {uploadSession && (
              <dl className="upload77-queue-summary" aria-label="上传会话进度">
                <div>
                  <dt>总数</dt>
                  <dd>{uploadSession.total_files}</dd>
                </div>
                <div>
                  <dt>已完成</dt>
                  <dd>{uploadSession.completed_files}</dd>
                </div>
                <div>
                  <dt>处理中</dt>
                  <dd>{uploadSession.processing_files}</dd>
                </div>
                <div>
                  <dt>等待中</dt>
                  <dd>{uploadSession.waiting_files}</dd>
                </div>
                <div>
                  <dt>失败</dt>
                  <dd>{uploadSession.failed_files}</dd>
                </div>
                <div>
                  <dt>批次</dt>
                  <dd>
                    {uploadSession.current_batch_number ?? uploadSession.total_batches}/
                    {uploadSession.total_batches}
                  </dd>
                </div>
              </dl>
            )}
            <div className="upload77-table-wrap">
              <table className="upload77-table">
                <thead>
                  <tr>
                    <th>文件</th>
                    <th>类型</th>
                    <th>大小</th>
                    <th>上传状态</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  {localUploadQueue.map((item) => {
                    const processingLabel = item.processingStage
                      ? PROCESSING_STAGE_LABELS[item.processingStage]
                      : undefined;
                    const label = {
                      queued: "等待上传",
                      uploading: "上传中",
                      processing: processingLabel ?? "派生处理中",
                      awaiting_confirmation: "规范文本已生成，待人工确认",
                      completed: "已完成",
                      cancelled: "已取消",
                      failed: "上传失败",
                    }[item.status];
                    return (
                      <tr key={item.id}>
                        <td>
                          {item.fileName}
                          {item.sameNameWarning && (
                            <span className="upload77-name-warning">同名，需确认</span>
                          )}
                        </td>
                        <td>{item.fileType}</td>
                        <td>{formatFileSize(item.fileSize)}</td>
                        <td>
                          <div className={`upload77-batch-progress is-${item.status}`}>
                            <span className="upload77-batch-state">{label}</span>
                            {item.batchNumber && <span>第 {item.batchNumber} 批</span>}
                            {Boolean(item.retryCount) && <span>第 {item.retryCount} 次恢复</span>}
                            {item.lastAttemptAt && (
                              <span>最近尝试 {formatBeijingTime(item.lastAttemptAt)}</span>
                            )}
                            {item.error && (
                              <span className="upload77-queue-error">{item.error}</span>
                            )}
                          </div>
                        </td>
                        <td>
                          {item.status === "failed" && (
                            <>
                              {item.retryable !== false && (
                                <button
                                  className="upload77-retry-link"
                                  onClick={() => retryLocalUpload(item.id)}
                                  type="button"
                                >
                                  重试
                                </button>
                              )}
                              <button
                                className="upload77-retry-link"
                                onClick={() => removeLocalUpload(item.id)}
                                type="button"
                              >
                                移除
                              </button>
                            </>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        </section>
      )}

      {/* 本地上传待确认任务：仅在无活跃文件时展示，点击直接进入核对入库流程 */}
      {!hasFile && (
        <section className="upload77-wecom" aria-labelledby="local-pending-title">
          <div className="upload77-section-head">
            <div>
              <h2 id="local-pending-title">待确认入库</h2>
              <p>以下为本地上传但尚未确认的资料，点击可继续确认流程。</p>
            </div>
            <div className="upload77-section-actions">
              <button
                className="btn-secondary upload77-icon-button"
                onClick={() => void loadLocalPending()}
                disabled={localPendingLoading}
                type="button"
              >
                <RefreshCw size={15} aria-hidden="true" />
                {localPendingLoading ? "刷新中" : "刷新"}
              </button>
              <button
                aria-controls="local-pending-body"
                aria-expanded={!isPendingCollapsed}
                className="upload77-icon-button"
                onClick={() => setIsPendingCollapsed((prev) => !prev)}
                title={isPendingCollapsed ? "展开待确认" : "折叠待确认"}
                type="button"
              >
                <ChevronDown
                  size={15}
                  aria-hidden="true"
                  className={isPendingCollapsed ? "is-collapsed" : ""}
                />
                <span className="upload77-icon-button-label">
                  {isPendingCollapsed ? "展开" : "折叠"}
                </span>
              </button>
              <PendingBatchActions tasks={localPendingTasks} flow={flow} />
              {pendingSelectionReason(localPendingTasks, flow) && (
                <span className="upload77-selection-reason" role="status">
                  {pendingSelectionReason(localPendingTasks, flow)}
                </span>
              )}
            </div>
          </div>
          <div
            id="local-pending-body"
            className={`upload77-section-body ${isPendingCollapsed ? "is-collapsed" : ""}`}
          >
            {localPendingLoading ? (
              <div className="upload77-state" role="status">
                正在加载待确认任务…
              </div>
            ) : localPendingError ? (
              <div className="upload77-state upload77-state-error" role="alert">
                <span>{localPendingError}</span>
                <button
                  className="btn-secondary"
                  onClick={() => void loadLocalPending()}
                  type="button"
                >
                  重试
                </button>
              </div>
            ) : localPendingTasks.length === 0 ? (
              <div className="upload77-state">
                <strong>暂无待确认资料</strong>
                <span>上传文件并点击「开始处理」后即在此显示。</span>
              </div>
            ) : (
              <div className="upload77-table-wrap">
                <table className="upload77-table upload77-pending-table">
                  <colgroup>
                    <col className="upload77-pending-col-select" />
                    <col className="upload77-pending-col-result" />
                    <col className="upload77-pending-col-file" />
                    <col className="upload77-pending-col-status" />
                    <col className="upload77-pending-col-subject" />
                    <col className="upload77-pending-col-generation" />
                    <col className="upload77-pending-col-time" />
                  </colgroup>
                  <thead>
                    <tr>
                      <th className="upload77-batch-col">
                        <PendingSelectAll tasks={localPendingTasks} flow={flow} />
                      </th>
                      <th>处理结果</th>
                      <th>文件</th>
                      <th>状态</th>
                      <th>建议主题</th>
                      <th>建议生成状态</th>
                      <th>时间</th>
                    </tr>
                  </thead>
                  <tbody>
                    {localPendingTasks.map((task) => {
                      const selected = taskId === task.id;
                      const loadingThis = selected && flowState === "processing";
                      const itemStatus = batchStatus[task.id];
                      const rejectFailure = Object.prototype.hasOwnProperty.call(
                        batchRejectRetryability,
                        task.id,
                      );
                      return (
                        <tr key={task.id} className={selected ? "is-selected" : ""}>
                          <td className="upload77-batch-col">
                            <input
                              aria-label={`选择 ${task.source_file_name}`}
                              checked={batchSelection.includes(task.id)}
                              disabled={
                                !isPendingTaskActionable(task, flow) ||
                                (rejectFailure && !batchRejectRetryability[task.id])
                              }
                              onChange={() => toggleBatchTask(task.id)}
                              type="checkbox"
                            />
                          </td>
                          <td className="upload77-batch-result">
                            {itemStatus && (
                              <BatchTaskProgress
                                state={itemStatus}
                                actionLabel={
                                  batchOperation === "reject" || rejectFailure
                                    ? "批量拒绝"
                                    : "批量确认"
                                }
                              />
                            )}
                            {batchErrors[task.id] && (
                              <span className="upload77-queue-error">{batchErrors[task.id]}</span>
                            )}
                            {itemStatus === "failed" &&
                              (!rejectFailure || batchRejectRetryability[task.id]) && (
                                <button
                                  className="upload77-retry-link"
                                  disabled={batchBusy}
                                  onClick={() =>
                                    void (batchOperation === "reject" || rejectFailure
                                      ? handleBatchReject([task])
                                      : setBatchTasksSelected([task.id], true))
                                  }
                                  type="button"
                                >
                                  {batchOperation === "reject" || rejectFailure
                                    ? "重试"
                                    : "重新选择目标"}
                                </button>
                              )}
                          </td>
                          <td>
                            <button
                              className="upload77-task-select"
                              title={task.source_file_name}
                              onClick={() => {
                                if (!loadingThis && !batchBusy) void handleSelectPendingTask(task);
                              }}
                              disabled={loadingThis || batchBusy}
                              type="button"
                            >
                              {task.source_file_name}
                            </button>
                          </td>
                          <td>
                            <span className={`upload77-status upload77-status-${task.status}`}>
                              {pendingStatusLabel[task.status] ?? "待处理"}
                            </span>
                            {task.processing_stage && (
                              <small>
                                {PROCESSING_STAGE_LABELS[task.processing_stage] ??
                                  task.processing_stage}
                              </small>
                            )}
                            {task.retryable && (
                              <button
                                className="upload77-retry-link"
                                disabled={pendingRetryId === task.id}
                                onClick={() => void retryPending(task.id)}
                                type="button"
                              >
                                {pendingRetryId === task.id ? "重试中…" : "重试此文件"}
                              </button>
                            )}
                            {pendingRetryError[task.id] && (
                              <span className="upload77-queue-error">
                                {pendingRetryError[task.id]}
                              </span>
                            )}
                          </td>
                          <td>
                            <span
                              className="upload77-pending-truncate"
                              title={task.suggested_title ?? undefined}
                            >
                              {task.suggested_title || "—"}
                            </span>
                          </td>
                          <td title={task.suggestion_generation_reason}>
                            {task.suggestion_generation_status === "generated"
                              ? "建议已生成"
                              : task.suggestion_generation_status === "needs_manual_completion"
                                ? "需人工补全"
                                : "建议待校正"}
                          </td>
                          <td title="最近尝试时间">
                            {task.updated_at ? formatBeijingTime(task.updated_at) : "—"}
                            {Boolean(task.retry_count) && (
                              <small>第 {task.retry_count} 次恢复</small>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </section>
      )}
    </>
  );
}
