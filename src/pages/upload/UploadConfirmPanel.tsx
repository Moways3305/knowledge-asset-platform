import { ArrowRight, CheckCircle2, XCircle } from "lucide-react";
import { Link } from "react-router-dom";
import ModelAdvancedSettings from "../../components/ModelAdvancedSettings";
import {
  confidentialityOptions,
  extractionLabel,
  targetLibraryOptions,
  type TargetLibrary,
} from "./uploadConstants";
import type { UploadFlow } from "./useUploadFlow";

const indexStatusLabel: Record<string, string> = {
  indexing: "已确认，WeKnora 正在处理；完成后才可检索",
  indexed: "WeKnora 处理完成，当前可检索",
  index_failed: "资产已保存，问答索引暂未完成",
  skipped: "资产已保存，未启用问答索引",
};

export function confirmationSubjectLabel(targetLibrary: TargetLibrary): string {
  if (!targetLibrary) return "建议主题";
  return targetLibrary === "project" || targetLibrary === "company" ? "主题" : "标题";
}

export default function UploadConfirmPanel({
  flow,
  onExit,
  onReject,
}: {
  flow: UploadFlow;
  onExit: () => void;
  onReject: () => void;
}) {
  const {
    sourceLabel,
    sourceFile,
    extraction,
    desensitization,
    naming,
    namingOptions,
    namingCategoryId,
    setNamingCategoryId,
    directoryKey,
    setDirectoryKey,
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
    confirmSubmitted,
    canSubmit,
    resultAssetId,
    awaitingProjectReview,
    submitIndexStatus,
    generationErrorCategory,
    regenerating,
    regenerationError,
    handleRegenerateSuggestions,
    handleSubmit,
    handleReset,
    models,
  } = flow;
  const summaryStatus = llmStatus?.summaryStatus ?? null;
  const generationRetryable =
    summaryStatus === "failed" &&
    (generationErrorCategory === "response_error" || generationErrorCategory === "timeout");
  const summaryStatusText =
    summaryStatus === "generated"
      ? "内容建议已生成"
      : summaryStatus === "pending_model_config"
        ? "摘要待生成：当前未配置内容生成模型。"
        : summaryStatus === "failed"
          ? generationRetryable
            ? "摘要生成失败，可点击下方按钮重新生成；若仍失败请稍后再试或联系管理员。"
            : "摘要生成失败，当前不可自动重试，请稍后再试或联系管理员检查内容生成模型配置。"
          : "内容建议处理中";

  if (confirmSubmitted) {
    return (
      <section className="upload77-result" aria-labelledby="upload-result-title">
        <CheckCircle2 size={28} aria-hidden="true" />
        <div>
          <h2 id="upload-result-title">
            {awaitingProjectReview ? "已提交，等待项目经理确认" : "入库提交已完成"}
          </h2>
          {awaitingProjectReview ? (
            <p>项目经理确认后，资料才会进入项目知识库并参与检索与问答。</p>
          ) : (
            <p>
              {submitIndexStatus
                ? (indexStatusLabel[submitIndexStatus] ?? "资产处理状态已更新")
                : "资产已经按当前入库规则处理。"}
            </p>
          )}
          <div className="upload77-result-actions">
            {awaitingProjectReview && <Link to="/review">查看审批状态</Link>}
            {!awaitingProjectReview && resultAssetId && (
              <Link to={`/knowledge/${resultAssetId}`}>
                查看资产 <ArrowRight size={14} aria-hidden="true" />
              </Link>
            )}
            <button className="btn-secondary" onClick={handleReset} type="button">
              继续上传
            </button>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section className="upload77-confirm" aria-labelledby="upload-confirm-title">
      <div className="upload77-confirm-head">
        <div>
          <span className="upload77-kicker">核对并确认</span>
          <h2 id="upload-confirm-title">内容建议预览</h2>
        </div>
        <span className="upload77-status upload77-status-ready">待确认</span>
      </div>

      <div className="upload77-confirm-layout">
        <div className="upload77-form-column">
          <div className={`upload77-summary-status upload77-summary-${summaryStatus ?? "pending"}`}>
            {summaryStatusText}
          </div>
          {generationRetryable && (
            <div className="upload77-regenerate">
              <button
                type="button"
                className="btn-small"
                disabled={regenerating}
                onClick={() => void handleRegenerateSuggestions()}
              >
                {regenerating ? "正在重新生成…" : "重新生成建议"}
              </button>
              {regenerationError && (
                <span className="upload77-regenerate-error" role="alert">
                  {regenerationError}
                </span>
              )}
            </div>
          )}

          <label className="upload77-field upload77-field-wide" htmlFor="upload77-edit-title">
            <span>{confirmationSubjectLabel(targetLibrary)}</span>
            <input
              id="upload77-edit-title"
              value={editTitle}
              onChange={(event) => setEditTitle(event.target.value)}
            />
          </label>

          <label className="upload77-field upload77-field-wide" htmlFor="upload77-edit-one-liner">
            <span>一句话摘要</span>
            <input
              id="upload77-edit-one-liner"
              value={editOneLiner}
              onChange={(event) => setEditOneLiner(event.target.value)}
            />
          </label>

          <label className="upload77-field upload77-field-wide" htmlFor="upload77-edit-summary">
            <span>详细摘要</span>
            <textarea
              id="upload77-edit-summary"
              rows={6}
              value={editSummary}
              onChange={(event) => setEditSummary(event.target.value)}
            />
          </label>

          <label className="upload77-field" htmlFor="upload77-edit-key-points">
            <span>关键知识点</span>
            <textarea
              id="upload77-edit-key-points"
              rows={5}
              value={editKeyPoints}
              placeholder="每行一条"
              onChange={(event) => setEditKeyPoints(event.target.value)}
            />
          </label>

          <label className="upload77-field" htmlFor="upload77-edit-tags">
            <span>标签</span>
            <textarea
              id="upload77-edit-tags"
              rows={5}
              value={editTags}
              placeholder="使用空格或顿号分隔"
              onChange={(event) => setEditTags(event.target.value)}
            />
          </label>
        </div>

        <aside className="upload77-confirm-side" aria-label="入库上下文与提交">
          <div className="upload77-context">
            <h3>资料信息</h3>
            <dl>
              <div>
                <dt>来源</dt>
                <dd>{sourceLabel}</dd>
              </div>
              <div>
                <dt>文件</dt>
                <dd>{sourceFile}</dd>
              </div>
              <div>
                <dt>建议生成状态</dt>
                <dd>
                  {suggestionGeneration?.status === "generated"
                    ? "建议已生成"
                    : suggestionGeneration?.status === "needs_manual_completion"
                      ? "需人工补全"
                      : "建议待校正"}
                </dd>
              </div>
              <div>
                <dt>状态依据</dt>
                <dd>{suggestionGeneration?.reason ?? "处理信息不足，请人工核对"}</dd>
              </div>
              <div>
                <dt>内容提取</dt>
                <dd>{extractionLabel[extraction?.status ?? ""] ?? "状态待确认"}</dd>
              </div>
              <div>
                <dt>敏感信息保护</dt>
                <dd>{desensitization?.message ?? desensitization?.status ?? "未返回状态"}</dd>
              </div>
            </dl>
          </div>

          {naming && (
            <details className="upload77-naming">
              <summary>主题提取依据</summary>
              <p>{naming.topic}</p>
              <span>
                {naming.inferred_fields.includes("topic") ? "主题由文件名推断" : "主题来自内容建议"}
              </span>
            </details>
          )}

          <div className="upload77-targets">
            <h3>入库目标</h3>
            <p className="upload77-field-note">已选资料 1 项</p>
            {!targetLibrary && (
              <p className="upload77-field-note" role="status">
                选择项目库或公司库后生成规范名
              </p>
            )}
            {targetLocked && (
              <p className="upload77-field-note" role="status">
                目标已由来源规则锁定
              </p>
            )}
            <label className="upload77-field" htmlFor="upload77-target-library">
              <span>目标知识库</span>
              <select
                id="upload77-target-library"
                value={targetLibrary}
                disabled={targetLocked}
                onChange={(event) => setTargetLibrary(event.target.value as TargetLibrary)}
              >
                {targetLibraryOptions
                  .filter(
                    (option) =>
                      option.value !== "project" ||
                      projects.length > 0 ||
                      targetLibrary === "project",
                  )
                  .filter(
                    (option) =>
                      option.value !== "company" ||
                      canUseCompanyTarget ||
                      targetLibrary === "company",
                  )
                  .map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
              </select>
            </label>
            {targetLibrary === "project" && (
              <label className="upload77-field" htmlFor="upload77-target-project">
                <span>目标项目</span>
                {projects.length > 0 ? (
                  <select
                    id="upload77-target-project"
                    value={targetProjectId}
                    disabled={targetLocked}
                    onChange={(event) => setTargetProjectId(event.target.value)}
                  >
                    <option value="">请选择目标项目</option>
                    {targetProjectId &&
                      !projects.some((project) => project.projectId === targetProjectId) && (
                        <option value={targetProjectId}>来源规则锁定项目（当前不可用）</option>
                      )}
                    {projects.map((project) => (
                      <option key={project.projectId} value={project.projectId}>
                        {project.projectName}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span className="upload77-field-error">当前没有可提交的项目</span>
                )}
              </label>
            )}
            {targetLibrary && (
              <label className="upload77-field" htmlFor="upload77-naming-confidentiality">
                <span>密级</span>
                <select
                  id="upload77-naming-confidentiality"
                  value={editConfidentiality}
                  onChange={(event) => setEditConfidentiality(event.target.value)}
                >
                  {confidentialityOptions.map((option) => (
                    <option key={option}>{option}</option>
                  ))}
                </select>
              </label>
            )}
            {targetLibrary === "personal" && (
              <p className="upload77-naming-exemption" role="status">
                个人资料不强制规范命名，保留原文件名用于来源追溯。
              </p>
            )}
            {targetLibrary && namingOptions?.directories?.length ? (
              <label className="upload77-field" htmlFor="upload77-directory">
                <span>最终目录</span>
                <select
                  id="upload77-directory"
                  value={directoryKey}
                  onChange={(event) => setDirectoryKey(event.target.value)}
                >
                  <option value="">请选择标准目录</option>
                  {namingOptions.directories
                    .filter((directory) => directory.directory_key !== "personal.pending")
                    .map((directory) => (
                      <option key={directory.directory_key} value={directory.directory_key}>
                        {directory.display_name}
                      </option>
                    ))}
                </select>
                <small>目录建议来自命名规则，最终选择由本次确认人决定。</small>
              </label>
            ) : null}
            {(targetLibrary === "project" || targetLibrary === "company") && namingRequired && (
              <div className="upload77-canonical-form" aria-label="规范命名字段">
                <label className="upload77-field" htmlFor="upload77-naming-category">
                  <span>目录类别</span>
                  <select
                    id="upload77-naming-category"
                    value={namingCategoryId}
                    onChange={(event) => setNamingCategoryId(event.target.value)}
                  >
                    <option value="">请选择目录类别</option>
                    {namingOptions?.categories.map((category) => (
                      <option key={category.id} value={category.id}>
                        {category.primary} / {category.secondary}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="upload77-field" htmlFor="upload77-naming-date">
                  <span>文件形成日期</span>
                  <input
                    id="upload77-naming-date"
                    type="date"
                    value={namingFormedOn}
                    onChange={(event) => setNamingFormedOn(event.target.value)}
                  />
                </label>
                <label className="upload77-field" htmlFor="upload77-naming-version">
                  <span>版本</span>
                  <input
                    id="upload77-naming-version"
                    value={namingVersion}
                    placeholder="V1 或 V1.1"
                    onChange={(event) => setNamingVersion(event.target.value.toUpperCase())}
                  />
                </label>
                {targetLibrary === "company" && (
                  <label className="upload77-field" htmlFor="upload77-naming-applicable">
                    <span>适用对象</span>
                    <input
                      id="upload77-naming-applicable"
                      value={namingApplicableTo}
                      onChange={(event) => setNamingApplicableTo(event.target.value)}
                    />
                  </label>
                )}
                <div className="upload77-canonical-preview" aria-live="polite">
                  <span>规范名预览</span>
                  {namingPreviewBusy ? (
                    <p>正在按已发布规则计算…</p>
                  ) : namingPreview?.canonical_name ? (
                    <code>{namingPreview.canonical_name}</code>
                  ) : (
                    <p>{namingPreviewError ?? "填写字段后生成预览"}</p>
                  )}
                  {namingPreview?.notices.map((notice) => (
                    <strong
                      className={`is-${notice.kind}`}
                      key={`${notice.kind}-${notice.message}`}
                    >
                      {notice.message}
                    </strong>
                  ))}
                </div>
              </div>
            )}
            {(targetLibrary === "project" || targetLibrary === "company") &&
              namingPreviewError &&
              !namingRequired && (
                <p className="upload77-field-error" role="alert">
                  {namingPreviewError}
                </p>
              )}
          </div>

          <ModelAdvancedSettings models={models} />

          {apiError && (
            <div className="upload77-submit-error" role="alert">
              {apiError}
            </div>
          )}
          <button
            className="btn-primary upload77-submit"
            disabled={!canSubmit}
            onClick={handleSubmit}
            type="button"
          >
            {(namingPreview?.notices.length ?? 0) > 0 ? "仍然确认入库" : "确认入库"}
          </button>
          <button className="upload77-reject" onClick={onReject} type="button">
            <XCircle size={14} aria-hidden="true" />
            拒绝入库
          </button>
          <button className="upload77-exit" onClick={onExit} type="button">
            退出
          </button>
        </aside>
      </div>
    </section>
  );
}
