import { Link } from "react-router-dom";
import {
  desensCategoryLabel,
  extractionLabel,
  flowLabel,
  formatFileSize,
} from "./uploadConstants";
import type { UploadFlow } from "./useUploadFlow";

// 路径 B：本地上传流程——流程状态条 + 上传入口 + 文本抽取结果 + 安全与脱敏。
export default function UploadStepB({ flow }: { flow: UploadFlow }) {
  const {
    flowState, fileName, fileSize, fileType, hasFile, extraction, desensitization,
    fileRef, handleFileSelect, handleStart, handleReset,
  } = flow;
  const flowMeta = flowLabel(flowState);

  return (
    <>
      {/* Flow status bar */}
      <div className={`up-flow-bar ${flowMeta.cls}`}>
        <span className="up-flow-indicator" />
        <span className="up-flow-text">{flowMeta.text}</span>
        {flowState === "processing" && <span className="up-flow-spinner" />}
        <span className="up-flow-note">真实上传 · 文件字节写入平台受控本地存储（dev）</span>
      </div>

      {/* Upload entry */}
      <section className="upload-section">
        <h3>上传入口</h3>
        {!hasFile ? (
          <div className="upload-dropzone" onClick={() => fileRef.current?.click()}>
            <input ref={fileRef} type="file" className="up-file-input" accept=".pptx,.pdf,.docx,.xlsx,.doc,.xls,.ppt" onChange={handleFileSelect} />
            <p className="dropzone-main">点击选择文件或拖拽到此区域</p>
            <p className="dropzone-hint">支持 .pptx .pdf .docx .xlsx 等格式，单文件最大 25 MiB</p>
            <div className="dropzone-security">
              <span className="dropzone-security-badge">受控上传</span>
              <span>选中文件的字节会上传至平台受控本地存储（dev）；后端只返回安全元数据，不返回存储路径或对象 URL</span>
            </div>
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
                <button className="btn-primary" onClick={handleStart}>开始资产化</button>
              )}
              {flowState === "processing" && (
                <button className="btn-secondary" disabled>处理中…</button>
              )}
              {(flowState === "file_selected" || flowState === "processing") && (
                <button className="btn-secondary" onClick={handleReset}>取消</button>
              )}
            </div>
          </div>
        )}

        {/* 文本抽取结果（真实抽取；后续内容处理由外部 LLM，失败时降级为确定性建议） */}
        {extraction && (
          <div className={`up-extraction up-extraction-${extraction.status ?? "unknown"}`}>
            <div className="up-extraction-head">
              <span className="up-extraction-label">文本抽取</span>
              <span className="up-extraction-status">{extractionLabel[extraction.status ?? ""] ?? extraction.status}</span>
              {extraction.charCount != null && extraction.status === "extracted" && (
                <span className="up-extraction-meta">{extraction.charCount} 字</span>
              )}
            </div>
            {extraction.isDuplicate && (
              <div className="up-extraction-dup">检测到内容相同的既有任务（软提示，不阻断）：任务 {extraction.duplicateTaskId}</div>
            )}
            {extraction.errorMessage && (
              <div className="up-extraction-error">{extraction.errorMessage}</div>
            )}
            {extraction.preview && (
              <pre className="up-extraction-preview">{extraction.preview}</pre>
            )}
          </div>
        )}
      </section>

      {/* Security & desensitization（短诚实边界，详情入帮助页） */}
      <section className="upload-section">
        <h3>安全与脱敏</h3>
        <p className="page-help-line">
          文本抽取与外部 LLM 内容处理<strong>已真实接入</strong>（不可用时 fail-closed 降级）；抽取成功后<strong>入库前已做规则实体脱敏</strong>，平台侧外部 LLM 内容建议仅使用脱敏后文本；不可抽取文本则无法做文本级前置脱敏。WeKnora 底座按已确认信任边界仍可接触原文做索引。未实现：OCR、结构保持式文件重写、Ollama/LLM 脱敏、历史资产全量重索引。详见 <Link to="/help#ingest" className="page-help-link">使用说明 →</Link>
        </p>
        {desensitization && desensitization.status && (
          <div className={`up-desensitization up-desensitization-${desensitization.status}`}>
            <span className="up-desensitization-label">前置脱敏</span>
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
      </section>
    </>
  );
}
