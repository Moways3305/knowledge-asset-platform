import type { Dispatch, SetStateAction } from "react";
import { Check, Trash2 } from "lucide-react";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type { BatchNamingValuesDTO, NamingOptionsDTO } from "../../types/naming";
import type { UploadFlow } from "./useUploadFlow";
import type { TargetLibrary } from "./uploadConstants";
import DuplicateComparisonPopover from "./DuplicateComparisonPopover";
import {
  hasReliableAiConfidentiality,
  previewError,
  rowMissing,
  suggestedConfidentiality,
  suggestedVersion,
} from "./pendingBatchReviewState";
import type {
  CompletedReviewItem,
  DeleteFeedback,
  PreviewRows,
  ReviewFilter,
  ReviewRows,
  ReviewState,
  SkippedDuplicateItem,
} from "./pendingBatchReviewState";

type FilterSnapshot = { filter: ReviewFilter; taskIds: string[] } | null;

type Props = {
  previewSummary: string;
  visibleConfirmTasks: PendingIngestItemDTO[];
  selectedConfirmTasks: PendingIngestItemDTO[];
  loading: boolean;
  refreshPreviews: () => Promise<void>;
  reviewFilter: ReviewFilter;
  setReviewFilter: Dispatch<SetStateAction<ReviewFilter>>;
  setFilterSnapshot: Dispatch<SetStateAction<FilterSnapshot>>;
  statesByTask: Record<string, ReviewState>;
  stateCounts: Record<ReviewFilter, number>;
  completedReviewItems: CompletedReviewItem[];
  warningNotices: unknown[];
  rows: ReviewRows;
  previews: PreviewRows;
  editedTaskIds: Set<string>;
  loadAiReview: (task: PendingIngestItemDTO, retry?: boolean) => Promise<void>;
  flow: UploadFlow;
  deletingTaskId: string | null;
  confirmingTaskId: string | null;
  setConfirmCandidate: Dispatch<SetStateAction<PendingIngestItemDTO | null>>;
  setDeleteCandidate: Dispatch<SetStateAction<PendingIngestItemDTO | null>>;
  deleteFeedback: Record<string, DeleteFeedback>;
  setDeleteFeedback: Dispatch<SetStateAction<Record<string, DeleteFeedback>>>;
  directoryLabel: (key: string) => string;
  updateRow: (taskId: string, patch: Partial<BatchNamingValuesDTO>) => void;
  company: boolean;
  options: NamingOptionsDTO | null;
  previewBusyByTask: Record<string, boolean>;
  previewFeedback: Record<string, string>;
  scheduleRowPreview: (taskId: string, row: BatchNamingValuesDTO) => void;
  targetLibrary: TargetLibrary;
  duplicateDecisionTaskId: string | null;
  skippedDuplicateItems: SkippedDuplicateItem[];
  onDuplicateDecision: (
    task: PendingIngestItemDTO,
    action: "skip" | "independent" | "keep",
  ) => Promise<void>;
};

export default function PendingBatchNamingReview(props: Props) {
  const {
    previewSummary,
    visibleConfirmTasks,
    selectedConfirmTasks,
    loading,
    refreshPreviews,
    reviewFilter,
    setReviewFilter,
    setFilterSnapshot,
    statesByTask,
    stateCounts,
    completedReviewItems,
    warningNotices,
    rows,
    previews,
    editedTaskIds,
    loadAiReview,
    flow,
    deletingTaskId,
    confirmingTaskId,
    setConfirmCandidate,
    setDeleteCandidate,
    deleteFeedback,
    setDeleteFeedback,
    directoryLabel,
    updateRow,
    company,
    options,
    previewBusyByTask,
    previewFeedback,
    scheduleRowPreview,
    targetLibrary,
    duplicateDecisionTaskId,
    skippedDuplicateItems,
    onDuplicateDecision,
  } = props;

  return (
    <div className="upload77-batch-naming-review">
      <div className="upload77-batch-naming-toolbar">
        <div>
          <span role="status">{previewSummary}</span>
          <span className="upload77-batch-filter-summary" role="status">
            当前筛选显示 {visibleConfirmTasks.length}/{selectedConfirmTasks.length} 条
          </span>
        </div>
        <div className="upload77-batch-naming-row-actions">
          <button
            className="btn-secondary"
            disabled={loading}
            onClick={() => void refreshPreviews()}
            type="button"
          >
            生成或刷新全部预览
          </button>
        </div>
      </div>
      <div className="upload77-batch-naming-filters" aria-label="核对状态筛选">
        {(
          [
            ["all", "全部"],
            ["ai_ready", "AI 已确定"],
            ["manual", "需人工补齐"],
            ["reviewed", "已核对"],
            ["exception", "异常/重复"],
          ] as const
        ).map(([value, label]) => (
          <button
            aria-pressed={reviewFilter === value}
            className="upload77-batch-filter"
            key={value}
            onClick={() => {
              setReviewFilter(value);
              setFilterSnapshot({
                filter: value,
                taskIds:
                  value === "all"
                    ? selectedConfirmTasks.map((task) => task.id)
                    : selectedConfirmTasks
                        .filter((task) => statesByTask[task.id] === value)
                        .map((task) => task.id),
              });
            }}
            type="button"
          >
            {label}（{stateCounts[value]}）
          </button>
        ))}
      </div>
      <div className="upload77-batch-naming-scroll">
        {skippedDuplicateItems.length > 0 && (
          <section className="upload77-batch-completed" aria-label="本次跳过的重复资料">
            <h4>本次不入库（{skippedDuplicateItems.length}）</h4>
            {skippedDuplicateItems.map(({ task, duplicate }) => (
              <article className="upload77-batch-completed-item" key={`skipped-${task.id}`}>
                <strong>{task.source_file_name}</strong>
                <DuplicateComparisonPopover
                  duplicate={duplicate}
                  current={{ fileName: task.source_file_name, fileSize: task.source_file_size }}
                  busy={duplicateDecisionTaskId === task.id}
                  onKeep={() => void props.onDuplicateDecision(task, "keep")}
                />
              </article>
            ))}
          </section>
        )}
        {completedReviewItems.length > 0 && (
          <section className="upload77-batch-completed" aria-labelledby="batch-completed-title">
            <h4 id="batch-completed-title">本次已入库（{completedReviewItems.length}）</h4>
            <div className="upload77-batch-completed-list">
              {completedReviewItems.map((item) => (
                <article className="upload77-batch-completed-item" key={item.taskId}>
                  <div>
                    <strong>{item.title}</strong>
                    <span role="status">
                      {item.indexStatus === "indexed"
                        ? "索引完成，可检索"
                        : item.indexStatus === "indexing"
                          ? "索引处理中"
                          : item.indexStatus === "index_failed"
                            ? "索引未完成，可恢复"
                            : item.indexStatus === "not_indexed"
                              ? "等待进入索引"
                              : item.indexStatus === "skipped"
                                ? "此前未进入索引"
                                : item.assetId
                                  ? "已入库"
                                  : "已提交，等待后续处理"}
                    </span>
                  </div>
                  {item.assetId && (
                    <a
                      aria-label={`查看知识资产卡片：${item.title}`}
                      className="btn-secondary"
                      href={`/knowledge/${encodeURIComponent(item.assetId)}`}
                      rel="noopener noreferrer"
                      target="_blank"
                    >
                      {item.indexStatus &&
                      ["index_failed", "not_indexed", "skipped"].includes(item.indexStatus)
                        ? "查看恢复状态"
                        : "查看知识资产卡片"}
                    </a>
                  )}
                </article>
              ))}
            </div>
          </section>
        )}
        {warningNotices.length > 0 && (
          <div className="upload77-batch-naming-notice" role="status">
            当前批次有 {warningNotices.length} 项命名或重复风险提示；确认后将作为独立资料入库，
            不会覆盖已有资产。
          </div>
        )}
        {visibleConfirmTasks.length === 0 && (
          <div className="upload77-batch-filter-empty" role="status">
            {selectedConfirmTasks.length === 0
              ? "本批待核对资料已处理完成，可查看本次结果或关闭弹窗"
              : "当前筛选下没有资料"}
          </div>
        )}
        {visibleConfirmTasks.map((task) => {
          const row = rows[task.id];
          const preview = previews[task.id];
          if (!row) return null;
          const localError = rowMissing(row, company);
          const serverError = previewError(preview);
          const fieldError = localError ?? serverError;
          return (
            <article className="upload77-batch-naming-row" key={task.id}>
              <header>
                <strong title={task.source_file_name}>
                  {selectedConfirmTasks.indexOf(task) + 1}. {task.source_file_name}
                </strong>
                <div className="upload77-batch-naming-row-actions">
                  <span>
                    {preview?.submittable
                      ? editedTaskIds.has(task.id)
                        ? "可确认"
                        : "已核对"
                      : "待核对"}
                  </span>
                  <button
                    className="btn-secondary"
                    onClick={() => void loadAiReview(task)}
                    type="button"
                  >
                    查看 AI 提取
                  </button>
                  <button
                    aria-label={`确认入库 ${task.source_file_name}`}
                    className="btn-primary upload77-batch-confirm-one"
                    disabled={
                      flow.batchBusy ||
                      deletingTaskId !== null ||
                      Boolean(rowMissing(row, company)) ||
                      !preview?.submittable
                    }
                    onClick={() => setConfirmCandidate(task)}
                    type="button"
                  >
                    <Check aria-hidden="true" size={14} />
                    确认入库
                  </button>
                  <button
                    aria-label={`删除 ${task.source_file_name}`}
                    className="upload77-batch-delete"
                    disabled={
                      !task.can_batch_reject ||
                      flow.batchBusy ||
                      confirmingTaskId !== null ||
                      deletingTaskId === task.id
                    }
                    onClick={() => {
                      setDeleteFeedback((current) => {
                        const next = { ...current };
                        delete next[task.id];
                        return next;
                      });
                      setDeleteCandidate(task);
                    }}
                    title={task.can_batch_reject ? "永久删除错误上传资料" : "当前资料不能永久删除"}
                    type="button"
                  >
                    <Trash2 aria-hidden="true" size={14} />
                    删除
                  </button>
                </div>
              </header>
              <DuplicateComparisonPopover
                duplicate={preview?.duplicate}
                current={{
                  fileName: task.source_file_name,
                  fileSize: task.source_file_size,
                  scopeLabel: targetLibrary === "company" ? "公司知识库" : "当前项目库",
                  directory: row.directory_key ? directoryLabel(row.directory_key) : null,
                  subject: row.subject,
                  formedOn: row.formed_on,
                  version: row.version,
                }}
                busy={duplicateDecisionTaskId === task.id}
                onSkip={() => void onDuplicateDecision(task, "skip")}
                onIndependent={() => void onDuplicateDecision(task, "independent")}
                onKeep={() => void onDuplicateDecision(task, "keep")}
              />
              {deleteFeedback[task.id] && (
                <div className="upload77-batch-delete-error" role="alert">
                  <span>{deleteFeedback[task.id].message}</span>
                  {deleteFeedback[task.id].retryable && (
                    <button onClick={() => setDeleteCandidate(task)} type="button">
                      重试删除
                    </button>
                  )}
                </div>
              )}
              <div className="upload77-batch-naming-grid">
                <label>
                  <span>主题</span>
                  <input
                    aria-label={`${task.source_file_name} 主题`}
                    value={row.subject}
                    onChange={(event) => updateRow(task.id, { subject: event.target.value })}
                  />
                  {fieldError?.field === "subject" && (
                    <small className="upload77-batch-naming-error">{fieldError.message}</small>
                  )}
                </label>
                <label>
                  <span>正式目录</span>
                  <select
                    aria-label={`${task.source_file_name} 正式目录`}
                    value={row.directory_key}
                    onChange={(event) => updateRow(task.id, { directory_key: event.target.value })}
                  >
                    <option value="">请选择</option>
                    {(options?.directories ?? [])
                      .filter((directory) => directory.scope === targetLibrary)
                      .map((directory) => (
                        <option key={directory.directory_key} value={directory.directory_key}>
                          {directory.display_name}
                        </option>
                      ))}
                  </select>
                  {fieldError?.field === "directory_key" && (
                    <small className="upload77-batch-naming-error">{fieldError.message}</small>
                  )}
                  <small className="upload77-batch-naming-notice">
                    该目录将作为资产归属与规范命名的唯一依据。
                  </small>
                </label>
                <label>
                  <span>文件形成日期</span>
                  <input
                    aria-label={`${task.source_file_name} 文件形成日期`}
                    type="date"
                    value={row.formed_on}
                    onChange={(event) => updateRow(task.id, { formed_on: event.target.value })}
                  />
                  {fieldError?.field === "formed_on" && (
                    <small className="upload77-batch-naming-error">{fieldError.message}</small>
                  )}
                </label>
                <label>
                  <span>版本</span>
                  <input
                    aria-label={`${task.source_file_name} 版本`}
                    placeholder="V1"
                    value={row.version}
                    onChange={(event) =>
                      updateRow(task.id, { version: event.target.value.toUpperCase() })
                    }
                  />
                  {fieldError?.field === "version" && (
                    <small className="upload77-batch-naming-error">{fieldError.message}</small>
                  )}
                  <small
                    className={`upload77-batch-naming-source ${
                      row.version !== suggestedVersion(task) ||
                      task.version_source === "default_needs_confirmation" ||
                      !task.version_source
                        ? "is-manual"
                        : ""
                    }`}
                  >
                    {row.version !== suggestedVersion(task)
                      ? "已人工修改"
                      : task.version_source === "source_filename"
                        ? "来自源文件"
                        : task.version_source === "ai_content"
                          ? "AI 建议"
                          : "规则默认，需核对"}
                  </small>
                </label>
                {company && (
                  <label>
                    <span>适用对象</span>
                    <input
                      aria-label={`${task.source_file_name} 适用对象`}
                      value={row.applicable_to ?? ""}
                      onChange={(event) =>
                        updateRow(task.id, { applicable_to: event.target.value })
                      }
                    />
                    {fieldError?.field === "applicable_to" && (
                      <small className="upload77-batch-naming-error">{fieldError.message}</small>
                    )}
                  </label>
                )}
                <label>
                  <span>密级</span>
                  <select
                    aria-label={`${task.source_file_name} 密级`}
                    value={row.confidentiality_level}
                    onChange={(event) =>
                      updateRow(task.id, { confidentiality_level: event.target.value })
                    }
                  >
                    {["L1", "L2", "L3", "L4", "L5"].map((level) => (
                      <option key={level}>{level}</option>
                    ))}
                  </select>
                  <small
                    className={`upload77-batch-naming-source ${
                      row.confidentiality_level !== suggestedConfidentiality(task, options!) ||
                      !hasReliableAiConfidentiality(task)
                        ? "is-manual"
                        : ""
                    }`}
                    title={task.confidentiality_reason ?? undefined}
                  >
                    {row.confidentiality_level !== suggestedConfidentiality(task, options!)
                      ? "已人工修改"
                      : hasReliableAiConfidentiality(task)
                        ? `AI 内容建议 · ${
                            task.confidentiality_confidence === "high" ? "高" : "中"
                          }置信度`
                        : "AI 未确定，规则默认，需核对"}
                  </small>
                </label>
              </div>
              <div
                className="upload77-batch-naming-preview"
                title={preview?.canonical_name ?? undefined}
              >
                <strong>规范名预览：</strong>
                {rowMissing(row, company)?.message
                  ? `${rowMissing(row, company)!.message}后生成规范名`
                  : previewBusyByTask[task.id]
                    ? "正在按当前填写内容生成…"
                    : (preview?.canonical_name ?? "正在准备规范名预览")}
              </div>
              {previewFeedback[task.id] && (
                <div className="upload77-batch-naming-error" role="alert">
                  {previewFeedback[task.id]}
                  {!localError && (
                    <button
                      className="upload77-batch-preview-retry"
                      onClick={() => scheduleRowPreview(task.id, row)}
                      type="button"
                    >
                      重试预览
                    </button>
                  )}
                </div>
              )}
              {serverError?.field === null && (
                <div className="upload77-batch-naming-error">
                  <span>{serverError.message}</span>
                </div>
              )}
              {preview?.notices.map((notice) => (
                <div
                  className="upload77-batch-naming-notice"
                  key={`${notice.kind}-${notice.message}`}
                >
                  {notice.message}
                </div>
              ))}
            </article>
          );
        })}
      </div>
    </div>
  );
}
