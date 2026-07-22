import { FileText, RefreshCw, UploadCloud, X } from "lucide-react";
import { extractionLabel, flowLabel, formatFileSize, pendingStatusLabel } from "./uploadConstants";
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
    handleRefreshProcessing,
    handleReset,
    apiError,
    processingNote,
    localPendingTasks,
    localPendingLoading,
    localPendingError,
    loadLocalPending,
    handleSelectPendingTask,
    taskId,
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
          onChange={handleFileSelect}
        />

        {!hasFile ? (
          <div
            className="upload-dropzone upload77-dropzone"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => {
              event.preventDefault();
              const file = event.dataTransfer.files[0];
              if (file) handleFileDrop(file);
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
                <button className="upload77-remove" onClick={handleReset} type="button">
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
                    return (
                      <tr key={task.id} className={selected ? "is-selected" : ""}>
                        <td>
                          <button
                            className="upload77-task-select"
                            onClick={() => {
                              if (!loadingThis) void handleSelectPendingTask(task);
                            }}
                            disabled={loadingThis}
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
