import { FileText, FolderOpen, RefreshCw, UploadCloud, X } from "lucide-react";
import { useState } from "react";
import UnifiedFileTasks from "./UnifiedFileTasks";
import ConfirmDialog from "../../components/ConfirmDialog";
import { extractionLabel, flowLabel, formatFileSize } from "./uploadConstants";

import type { UploadFlow } from "./useUploadFlow";

export default function UploadStepB({ flow }: { flow: UploadFlow }) {
  const {
    flowState,
    taskId,
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
    pendingSelection,
    confirmPendingSelection,
    discardPendingSelection,
    handleStart,
    handleRefreshProcessing,
    handleReset,
    handleDeletePending,
    apiError,
    processingNote,
    localPendingTasks,
  } = flow;
  const [isDragging, setIsDragging] = useState(false);
  const pendingCounts = localPendingTasks.reduce(
    (counts, task) => {
      if (task.processing_stage === "ocr_queued") counts.queued += 1;
      else if (task.processing_stage === "processing_interrupted") counts.interrupted += 1;
      else if (task.status === "failed") counts.failed += 1;
      else if (task.status === "pending_confirmation") counts.succeeded += 1;
      return counts;
    },
    { queued: 0, interrupted: 0, failed: 0, succeeded: 0 },
  );
  const flowMeta = flowLabel(flowState);
  const canRefresh = flowState === "processing" && Boolean(processingNote);
  const extractionStatusText = extractionLabel[extraction?.status ?? ""] ?? "状态待确认";

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

        {pendingSelection && (
          <ConfirmDialog
            open
            title={`已选择 ${pendingSelection.items.length} 个文件`}
            description="确认后才开始上传；取消不会创建上传任务。"
            confirmText="开始上传"
            cancelText="取消选择"
            onConfirm={confirmPendingSelection}
            onCancel={discardPendingSelection}
            portal
          >
            <p>
              总大小：
              {formatFileSize(
                pendingSelection.items.reduce(
                  (sum, item) => sum + ("file" in item ? item.file.size : item.size),
                  0,
                ),
              )}
            </p>
            <ul className="upload-file-selection-list">
              {pendingSelection.items.map((item, index) => (
                <li key={index}>{"file" in item ? item.file.name : item.name}</li>
              ))}
            </ul>
          </ConfirmDialog>
        )}

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
            {localPendingTasks.length > 0 && (
              <p className="upload77-selection-reason" aria-label="入库处理状态统计">
                排队 {pendingCounts.queued} · 中断 {pendingCounts.interrupted} · 失败{" "}
                {pendingCounts.failed} · 已处理 {pendingCounts.succeeded}
              </p>
            )}
            <UploadCloud size={30} strokeWidth={1.7} aria-hidden="true" />
            <h2>{isDragging ? "松开即可逐项检查" : "拖放文件到这里"}</h2>
            <p className="dropzone-hint">
              支持 Markdown、PDF、Word（DOC/DOCX）、PPT/PPTX、Excel、纯文本等资料，单文件最大 100
              MB；DOC/PPT 自动转换并提取正文，纯图片内容可能需要人工补全
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

      {!hasFile && <UnifiedFileTasks flow={flow} />}
    </>
  );
}
