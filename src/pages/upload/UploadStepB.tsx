import { Link } from "react-router-dom";
import { desensCategoryLabel, extractionLabel, flowLabel, formatFileSize } from "./uploadConstants";
import type { UploadFlow } from "./useUploadFlow";

// 本地上传流程：状态条、上传入口、文本抽取结果与敏感信息保护提示。
export default function UploadStepB({ flow }: { flow: UploadFlow }) {
  const {
    flowState,
    fileName,
    fileSize,
    fileType,
    hasFile,
    extraction,
    desensitization,
    fileRef,
    handleFileSelect,
    handleStart,
    handleReset,
  } = flow;
  const flowMeta = flowLabel(flowState);

  return (
    <>
      {/* Upload entry */}
      <div className="upload-input-region">
        {!hasFile ? (
          <div className="upload-dropzone" onClick={() => fileRef.current?.click()}>
            <input
              ref={fileRef}
              type="file"
              className="up-file-input"
              accept=".md,.markdown,.txt,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx"
              onChange={handleFileSelect}
            />
            <p className="dropzone-main">点击选择文件或拖拽到此区域</p>
            <p className="dropzone-hint">
              支持 Markdown、PDF、Word、PPT、Excel、纯文本等资料，单文件最大 25 MiB
            </p>
          </div>
        ) : (
          <div className="up-file-info">
            <div className="up-file-detail">
              <div className="up-file-name">{fileName}</div>
              <div className="up-file-meta">
                <span>{formatFileSize(fileSize)}</span>
                <span>{fileType}</span>
              </div>
            </div>
            <div className="up-file-actions">
              {flowState === "file_selected" && (
                <button className="btn-primary" onClick={handleStart}>
                  开始资产化
                </button>
              )}
              {flowState === "processing" && (
                <button className="btn-secondary" disabled>
                  处理中…
                </button>
              )}
              {(flowState === "file_selected" || flowState === "processing") && (
                <button className="btn-secondary" onClick={handleReset}>
                  取消
                </button>
              )}
            </div>
          </div>
        )}

        {hasFile && (
          <div className={`up-flow-bar ${flowMeta.cls}`}>
            <span className="up-flow-indicator" />
            <span className="up-flow-text">{flowMeta.text}</span>
            {flowState === "processing" && <span className="up-flow-spinner" />}
            <span className="up-flow-note">文件已进入平台受控存储</span>
          </div>
        )}

        {/* 文本抽取结果 */}
        {extraction && (
          <div className={`up-extraction up-extraction-${extraction.status ?? "unknown"}`}>
            <div className="up-extraction-head">
              <span className="up-extraction-label">文本抽取</span>
              <span className="up-extraction-status">
                {extractionLabel[extraction.status ?? ""] ?? extraction.status}
              </span>
              {extraction.charCount != null && extraction.status === "extracted" && (
                <span className="up-extraction-meta">{extraction.charCount} 字</span>
              )}
            </div>
            {extraction.isDuplicate && (
              <div className="up-extraction-dup">
                检测到内容相同的既有任务（软提示，不阻断）：任务 {extraction.duplicateTaskId}
              </div>
            )}
            {extraction.errorMessage && (
              <div className="up-extraction-error">{extraction.errorMessage}</div>
            )}
            {extraction.preview && (
              <pre className="up-extraction-preview">{extraction.preview}</pre>
            )}
          </div>
        )}
      </div>

      {/* Security boundary（短诚实边界，详情入帮助页） */}
      <div className="upload-inline-info">
        <p>
          原文与内容建议受访问控制保护；命名、保密级别与异常处理详见{" "}
          <Link to="/help#ingest" className="page-help-link">
            使用说明 →
          </Link>
        </p>
        {desensitization && desensitization.status && (
          <div className={`up-desensitization up-desensitization-${desensitization.status}`}>
            <span className="up-desensitization-label">敏感信息保护</span>
            <span className="up-desensitization-status">
              {desensitization.message ?? desensitization.status}
            </span>
            {desensitization.counts && Object.keys(desensitization.counts).length > 0 && (
              <span className="up-desensitization-counts">
                {Object.entries(desensitization.counts)
                  .map(([cat, n]) => `${desensCategoryLabel[cat] ?? cat}×${n}`)
                  .join("，")}
              </span>
            )}
          </div>
        )}
      </div>
    </>
  );
}
