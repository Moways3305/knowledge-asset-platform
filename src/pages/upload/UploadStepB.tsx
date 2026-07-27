import { FileText, RefreshCw, UploadCloud, X } from "lucide-react";
import { extractionLabel, flowLabel, formatFileSize, pendingStatusLabel } from "./uploadConstants";
import BatchTaskProgress from "./BatchTaskProgress";
import { formatBeijingTime } from "../../utils/time";
import type { UploadFlow } from "./useUploadFlow";

export default function UploadStepB({ flow }: { flow: UploadFlow }) {
  const {
    flowState,
    fileName,
    fileSize,
    fileType,
    hasFile,
    extraction,
    fileRef,
    handleFileSelect,
    handleFileDrop,
    handleStart,
    localUploadQueue,
    retryLocalUpload,
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
    toggleBatchTask,
    handleBatchConfirm,
  } = flow;
  const flowMeta = flowLabel(flowState);
  const canRefresh = flowState === "processing" && Boolean(processingNote);

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

        {!hasFile ? (
          <div
            className="upload-dropzone upload77-dropzone"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              if (event.dataTransfer.files.length) handleFileDrop(event.dataTransfer.files);
            }}
          >
            <UploadCloud size={30} strokeWidth={1.7} aria-hidden="true" />
            <h2>拖放文件到这里</h2>
            <p className="dropzone-hint">
              支持 Markdown、PDF、Word、PPT、Excel、纯文本等资料，单文件最大 25 MiB
            </p>
            <button className="btn-primary" onClick={() => fileRef.current?.click()} type="button">
              选择文件
            </button>
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
                <strong>{extractionLabel[extraction.status ?? ""] ?? "状态待确认"}</strong>
                {extraction.charCount != null && extraction.status === "extracted" && (
                  <span>{extraction.charCount} 字</span>
                )}
                {extraction.isDuplicate && <span className="is-warning">检测到可能重复的资料</span>}
              </div>
            )}
          </div>
        )}
      </div>

      {!hasFile && localUploadQueue.length > 0 && (
        <section className="upload77-local-queue" aria-labelledby="local-upload-queue-title">
          <div className="upload77-section-head">
            <div>
              <h2 id="local-upload-queue-title">本次上传队列</h2>
              <p>每份文件独立上传；失败文件不会阻塞后续文件，可单独重试。</p>
            </div>
          </div>
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
                  const progress =
                    item.status === "queued" ? 0 : item.status === "uploading" ? 50 : 100;
                  const label = {
                    queued: "已入队",
                    uploading: "上传中",
                    awaiting_confirmation: "待确认入库",
                    failed: "上传失败",
                  }[item.status];
                  return (
                    <tr key={item.id}>
                      <td>{item.fileName}</td>
                      <td>{item.fileType}</td>
                      <td>{formatFileSize(item.fileSize)}</td>
                      <td>
                        <div className={`upload77-batch-progress is-${item.status}`}>
                          <span className="upload77-batch-state">{label}</span>
                          <progress
                            aria-label={`上传进度：${item.fileName}`}
                            className={item.status === "failed" ? "is-failed" : undefined}
                            max={100}
                            value={progress}
                          />
                          {item.error && <span className="upload77-queue-error">{item.error}</span>}
                        </div>
                      </td>
                      <td>
                        {item.status === "failed" && (
                          <button
                            className="upload77-retry-link"
                            onClick={() => retryLocalUpload(item.id)}
                            type="button"
                          >
                            重试
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
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
            <button
              className="btn-secondary upload77-icon-button"
              onClick={() => void loadLocalPending()}
              disabled={localPendingLoading}
              type="button"
            >
              <RefreshCw size={15} aria-hidden="true" />
              {localPendingLoading ? "刷新中" : "刷新"}
            </button>
            {batchSelection.length > 0 && (
              <button
                className="btn-primary"
                disabled={batchBusy}
                onClick={() =>
                  void handleBatchConfirm(
                    localPendingTasks.filter((task) => batchSelection.includes(task.id)),
                  )
                }
                type="button"
              >
                {batchBusy ? "正在逐条确认" : `批量确认入库（${batchSelection.length}）`}
              </button>
            )}
          </div>

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
              <table className="upload77-table">
                <thead>
                  <tr>
                    <th className="upload77-batch-col">批量</th>
                    <th>文件</th>
                    <th>状态</th>
                    <th>建议标题</th>
                    <th>置信度</th>
                    <th>时间</th>
                  </tr>
                </thead>
                <tbody>
                  {localPendingTasks.map((task) => {
                    const selected = taskId === task.id;
                    const loadingThis = selected && flowState === "processing";
                    const itemStatus = batchStatus[task.id];
                    return (
                      <tr key={task.id} className={selected ? "is-selected" : ""}>
                        <td className="upload77-batch-col">
                          <input
                            aria-label={`选择 ${task.source_file_name}`}
                            checked={batchSelection.includes(task.id)}
                            disabled={batchBusy || itemStatus === "success"}
                            onChange={() => toggleBatchTask(task.id)}
                            type="checkbox"
                          />
                          {itemStatus && <BatchTaskProgress state={itemStatus} />}
                          {itemStatus === "failed" && (
                            <button
                              className="upload77-retry-link"
                              disabled={batchBusy}
                              onClick={() => void handleBatchConfirm([task])}
                              type="button"
                            >
                              重试
                            </button>
                          )}
                        </td>
                        <td>
                          <button
                            className="upload77-task-select"
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
                        </td>
                        <td>{task.suggested_title || "—"}</td>
                        <td>
                          {task.confidence == null ? "—" : `${Math.round(task.confidence * 100)}%`}
                        </td>
                        <td>{task.created_at ? formatBeijingTime(task.created_at) : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
    </>
  );
}
