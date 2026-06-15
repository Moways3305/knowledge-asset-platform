import { Link } from "react-router-dom";
import {
  aiAccessOptions,
  assetTypeOptions,
  bizStageOptions,
  confidentialityOptions,
  targetLibraryOptions,
  visibilityOptions,
  type TargetLibrary,
} from "./uploadConstants";
import type { UploadFlow } from "./useUploadFlow";

// 共享确认区：来源上下文 + AI 生成预览 + 人工校正 + AI 建议目标库 + 提交动作 / 结果提示。
// 仅在 confirmReady / confirmSubmitted 时由页面渲染。
export default function UploadConfirmPanel({ flow }: { flow: UploadFlow }) {
  const {
    activePath, sourceLabel, sourceFile, editTitle, setEditTitle,
    editOneLiner, setEditOneLiner, editSummary, setEditSummary,
    editKeyPoints, setEditKeyPoints, editTags, setEditTags,
    editVisibility, setEditVisibility, editBizStage, setEditBizStage,
    editAssetType, setEditAssetType, editConfidentiality, setEditConfidentiality,
    editAiAccess, setEditAiAccess, targetLibrary, setTargetLibrary,
    targetProjectId, setTargetProjectId, projects, confirmConfidence,
    llmStatus, apiError, processingNote, confirmReady, confirmSubmitted, canSubmit,
    resultAssetId, submitIndexStatus, handleSubmit, handleReset,
  } = flow;

  return (
    <>
      {/* Source context bar */}
      <div className="up-source-bar">
        <span className={`ig-src-badge ${activePath === "a" ? "ig-src-wecom" : "ig-src-local"}`}>{sourceLabel}</span>
        <span className="up-source-file">{sourceFile}</span>
      </div>

      {/* AI preview card */}
      <section className="upload-section">
        <h3>AI 生成预览</h3>
        <div className="preview-card">
          <div className="card-header">
            <span className="card-title">{editTitle}</span>
            <div className="card-header-badges">
              <span className="asset-type-badge">交付物</span>
              <span className="visibility-badge project-only">{editVisibility}</span>
            </div>
          </div>
          <p className="card-summary">{editSummary}</p>
          <div className="card-tags">
            {editTags.split(/[·,，、\s]+/).filter(Boolean).map((t) => (
              <span key={t} className="tag">{t.trim()}</span>
            ))}
          </div>
          <div className="card-meta">
            <span>置信度 {confirmConfidence}</span>
            <span>来源：{sourceFile}</span>
            <span>来源渠道：{sourceLabel}</span>
          </div>
          <p className="preview-hint">* 以上为真实抽取 + 外部 LLM 内容处理建议（失败时降级为确定性建议），下方可编辑校正</p>
        </div>
      </section>

      {/* Human correction */}
      <section className="upload-section">
        <h3>人工校正</h3>
        <p className="correction-hint">
          {confirmReady
            ? "以下字段来自真实抽取 + 外部 LLM 内容处理（降级时为确定性建议），可直接编辑修改后提交。"
            : "处理中 / 已提交 / 处理失败时字段不可编辑。"}
        </p>
        {llmStatus && (
          <div className={`up-llm-status up-llm-${llmStatus.status ?? "unknown"}`}>
            {llmStatus.status === "llm"
              ? `内容建议由外部 LLM 生成（${llmStatus.provider ?? "—"}）`
              : "外部 LLM 未启用或调用失败，已降级为确定性建议，请人工补全三层摘要"}
          </div>
        )}
        <div className="correction-grid">
          <div className="correction-row">
            <div className="correction-field">标题</div>
            <div className="correction-value">
              {confirmReady ? (
                <input className="up-edit-input" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} />
              ) : (
                <span className="up-edit-disabled">{editTitle}</span>
              )}
            </div>
            <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
              {confirmReady ? "可编辑" : "只读"}
            </div>
          </div>
          <div className="correction-row">
            <div className="correction-field">一句话摘要</div>
            <div className="correction-value">
              {confirmReady ? (
                <input className="up-edit-input" value={editOneLiner} onChange={(e) => setEditOneLiner(e.target.value)} />
              ) : (
                <span className="up-edit-disabled">{editOneLiner}</span>
              )}
            </div>
            <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
              {confirmReady ? "可编辑" : "只读"}
            </div>
          </div>
          <div className="correction-row">
            <div className="correction-field">详细摘要</div>
            <div className="correction-value">
              {confirmReady ? (
                <textarea className="up-edit-textarea" value={editSummary} onChange={(e) => setEditSummary(e.target.value)} />
              ) : (
                <span className="up-edit-disabled">{editSummary}</span>
              )}
            </div>
            <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
              {confirmReady ? "可编辑" : "只读"}
            </div>
          </div>
          <div className="correction-row">
            <div className="correction-field">关键知识点<br /><span className="correction-hint">每行一条</span></div>
            <div className="correction-value">
              {confirmReady ? (
                <textarea className="up-edit-textarea" value={editKeyPoints} placeholder="每行一条关键知识点" onChange={(e) => setEditKeyPoints(e.target.value)} />
              ) : (
                <span className="up-edit-disabled">{editKeyPoints}</span>
              )}
            </div>
            <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
              {confirmReady ? "可编辑" : "只读"}
            </div>
          </div>
          <div className="correction-row">
            <div className="correction-field">标签</div>
            <div className="correction-value">
              {confirmReady ? (
                <input className="up-edit-input" value={editTags} onChange={(e) => setEditTags(e.target.value)} />
              ) : (
                <span className="up-edit-disabled">{editTags}</span>
              )}
            </div>
            <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
              {confirmReady ? "可编辑" : "只读"}
            </div>
          </div>
          <div className="correction-row">
            <div className="correction-field">可见性</div>
            <div className="correction-value">
              {confirmReady ? (
                <select className="up-edit-select" value={editVisibility} onChange={(e) => setEditVisibility(e.target.value)}>
                  {visibilityOptions.map((o) => <option key={o}>{o}</option>)}
                </select>
              ) : (
                <span className="up-edit-disabled">{editVisibility}</span>
              )}
            </div>
            <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
              {confirmReady ? "可编辑" : "只读"}
            </div>
          </div>
          <div className="correction-row">
            <div className="correction-field">业务阶段</div>
            <div className="correction-value">
              {confirmReady ? (
                <select className="up-edit-select" value={editBizStage} onChange={(e) => setEditBizStage(e.target.value)}>
                  {bizStageOptions.map((o) => <option key={o}>{o}</option>)}
                </select>
              ) : (
                <span className="up-edit-disabled">{editBizStage}</span>
              )}
            </div>
            <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>
              {confirmReady ? "可编辑" : "只读"}
            </div>
          </div>
          <div className="correction-row">
            <div className="correction-field">资产类型</div>
            <div className="correction-value">
              {confirmReady ? (
                <select className="up-edit-select" value={editAssetType} onChange={(e) => setEditAssetType(e.target.value)}>
                  {assetTypeOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              ) : (
                <span className="up-edit-disabled">{assetTypeOptions.find((o) => o.value === editAssetType)?.label ?? editAssetType}</span>
              )}
            </div>
            <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>{confirmReady ? "可编辑" : "只读"}</div>
          </div>
          <div className="correction-row">
            <div className="correction-field">保密级别</div>
            <div className="correction-value">
              {confirmReady ? (
                <select className="up-edit-select" value={editConfidentiality} onChange={(e) => setEditConfidentiality(e.target.value)}>
                  {confidentialityOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <span className="up-edit-disabled">{editConfidentiality}</span>
              )}
            </div>
            <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>{confirmReady ? "可编辑" : "只读"}</div>
          </div>
          <div className="correction-row">
            <div className="correction-field">AI 调用级别</div>
            <div className="correction-value">
              {confirmReady ? (
                <select className="up-edit-select" value={editAiAccess} onChange={(e) => setEditAiAccess(e.target.value)}>
                  {aiAccessOptions.map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : (
                <span className="up-edit-disabled">{editAiAccess}</span>
              )}
            </div>
            <div className={`correction-status ${confirmReady ? "editable" : "readonly"}`}>{confirmReady ? "可编辑" : "只读"}</div>
          </div>
          <div className="correction-row">
            <div className="correction-field">置信度</div>
            <div className="correction-value">
              <span className="up-edit-disabled">{confirmConfidence}</span>
            </div>
            <div className="correction-status readonly">只读</div>
          </div>
        </div>
      </section>

      {/* AI recommendation + actions */}
      <section className="upload-section">
        <h3>AI 建议目标知识库</h3>
        <p className="correction-hint">
          {confirmReady
            ? "以下目标由 AI 根据文件内容、项目上下文与可见性自动推荐。如有偏差，可直接修正。"
            : "已提交，目标不可修改。"}
        </p>
        <div className="up-target-library">
          <label className="up-target-label">AI 建议</label>
          {confirmReady ? (
            <select
              className="up-edit-select"
              value={targetLibrary}
              onChange={(e) => setTargetLibrary(e.target.value as TargetLibrary)}
            >
              {targetLibraryOptions.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          ) : (
            <span className="up-edit-disabled">
              {targetLibraryOptions.find((o) => o.value === targetLibrary)!.label}
            </span>
          )}
          {confirmReady && <span className="up-target-adjust-hint">如不准确可修改</span>}
        </div>
        {targetLibrary === "project" && confirmReady && (
          <div className="up-target-library">
            <label className="up-target-label">目标项目</label>
            {projects.length > 0 ? (
              <select
                className="up-edit-select"
                value={targetProjectId}
                onChange={(e) => setTargetProjectId(e.target.value)}
              >
                {projects.map((p) => (
                  <option key={p.projectId} value={p.projectId}>{p.projectName}</option>
                ))}
              </select>
            ) : (
              <span className="up-edit-disabled">你不是任何项目的有效成员，无法提交到项目知识库</span>
            )}
          </div>
        )}
        <p className="page-help-line">
          目标库与资料区 / 资产区分区规则、入库 / 审核分流说明见 <Link to="/help#ingest" className="page-help-link">使用说明 →</Link>
        </p>
        {apiError && <div className="up-submit-notice" style={{ color: "var(--color-danger-fg, #b00)" }}>{apiError}</div>}
        {processingNote && (
          <div className="up-submit-notice" style={{ color: "var(--color-warning-fg, #8a6d00)" }}>{processingNote}</div>
        )}
        <div className="detail-actions-bar">
          <button className="btn-primary" disabled={!canSubmit} onClick={handleSubmit}>提交入库</button>
          <button className="btn-secondary" disabled>保存草稿</button>
          <button className="btn-secondary" onClick={handleReset}>{confirmSubmitted ? "再入库一条" : "取消"}</button>
        </div>
        {confirmSubmitted && resultAssetId && (
          submitIndexStatus === "index_failed" ? (
            <div className="up-submit-notice" style={{ color: "var(--color-warning-fg, #8a6d00)" }}>
              已确认入库并保存校正内容（zone = material），但知识底座索引暂未完成，稍后可重试或联系管理员；在此之前该资产可能暂不可被语义检索召回。
              <Link to={`/knowledge/${resultAssetId}`}>查看新资产 →</Link>
            </div>
          ) : (
            <div className="up-submit-notice">
              已真实入库（zone = material）{submitIndexStatus === "skipped" ? "；知识底座未启用，已跳过索引" : ""}。
              <Link to={`/knowledge/${resultAssetId}`}>查看新资产 →</Link>
            </div>
          )
        )}
      </section>
    </>
  );
}
