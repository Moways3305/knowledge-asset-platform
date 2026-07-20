import { FileText, RefreshCw, UploadCloud, X } from "lucide-react";
import { extractionLabel, flowLabel, formatFileSize } from "./uploadConstants";
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
  } = flow;
  const flowMeta = flowLabel(flowState);
  const canRefresh = flowState === "processing" && Boolean(processingNote);

  return (
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
            {flowState === "processing" && !processingNote && <span className="up-flow-spinner" />}
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
  );
}
