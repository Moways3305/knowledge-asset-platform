import { useMemo, useState } from "react";
import { Trash2 } from "lucide-react";
import ConfirmDialog from "../../components/ConfirmDialog";
import { ApiError } from "../../api/http";
import { fetchNamingOptions, previewBatchIngestNaming } from "../../api/naming";
import type { PendingIngestItemDTO } from "../../types/ingest";
import type {
  BatchNamingPreviewItemDTO,
  BatchNamingValuesDTO,
  NamingOptionsDTO,
} from "../../types/naming";
import type { UploadFlow } from "./useUploadFlow";
import type { TargetLibrary } from "./uploadConstants";
import { suggestNamingCategory } from "./namingCategorySuggestion";

type ReviewRows = Record<string, BatchNamingValuesDTO>;
type PreviewRows = Record<string, BatchNamingPreviewItemDTO>;
type ReviewFilter = "all" | "ai_ready" | "manual" | "reviewed" | "exception";
type ReviewState = Exclude<ReviewFilter, "all">;
type DeleteFeedback = { message: string; retryable: boolean };

const DATE_PATTERN = /^\d{4}-\d{2}-\d{2}$/;
const VERSION_PATTERN = /^V[1-9]\d*(?:\.[1-9]\d*)*$/;

function parsedValue(task: PendingIngestItemDTO, field: "date" | "version"): string {
  const parsed = task.naming_parsed_fields;
  if (!parsed || parsed.missing_fields?.includes(field)) return "";
  const value = parsed[field]?.trim() ?? "";
  if (field === "date") {
    if (DATE_PATTERN.test(value)) return value;
    if (/^\d{8}$/.test(value)) return `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6)}`;
    return "";
  }
  return VERSION_PATTERN.test(value.toUpperCase()) ? value.toUpperCase() : "";
}

function sourceSubject(task: PendingIngestItemDTO): string {
  // The original filename is displayed as source context only. Do not turn it
  // into a governed subject unless the backend has already projected a safe suggestion.
  return task.suggested_title?.trim() || "";
}

function initialRows(tasks: PendingIngestItemDTO[], options: NamingOptionsDTO): ReviewRows {
  return Object.fromEntries(
    tasks.map((task) => [
      task.id,
      {
        category_id: suggestNamingCategory(task.naming_parsed_fields, options.categories)?.id ?? "",
        subject: sourceSubject(task),
        formed_on: parsedValue(task, "date"),
        version: parsedValue(task, "version"),
        applicable_to: "",
        confidentiality_level: options.default_confidentiality || "L2",
      },
    ]),
  );
}

type NamingField = "subject" | "category_id" | "formed_on" | "version" | "applicable_to";

type RowError = { field: NamingField | null; message: string };

function rowMissing(row: BatchNamingValuesDTO, company: boolean): RowError | null {
  if (!row.subject.trim()) return { field: "subject", message: "请填写主题" };
  if (!row.category_id) return { field: "category_id", message: "请选择目录类别" };
  if (!DATE_PATTERN.test(row.formed_on)) {
    return { field: "formed_on", message: "请填写文件形成日期" };
  }
  if (!VERSION_PATTERN.test(row.version.toUpperCase())) {
    return { field: "version", message: "请填写有效版本，例如 V1" };
  }
  if (company && !row.applicable_to?.trim()) {
    return { field: "applicable_to", message: "请填写适用对象" };
  }
  return null;
}

function previewError(preview: BatchNamingPreviewItemDTO | undefined): RowError | null {
  if (!preview?.message || preview.submittable) return null;
  const fields: Partial<Record<string, NamingField>> = {
    naming_subject_invalid: "subject",
    naming_category_unavailable: "category_id",
    naming_formed_on_invalid: "formed_on",
    naming_version_invalid: "version",
    naming_applicable_to_required: "applicable_to",
  };
  return { field: fields[preview.error_code ?? ""] ?? null, message: preview.message };
}

function reviewState(
  task: PendingIngestItemDTO,
  row: BatchNamingValuesDTO,
  preview: BatchNamingPreviewItemDTO | undefined,
  categories: NamingOptionsDTO["categories"],
  company: boolean,
  flowError: string | undefined,
): ReviewState {
  if (preview?.error_code || preview?.notices.some((notice) => notice.kind === "exact")) {
    return "exception";
  }
  if (preview?.submittable) return "reviewed";
  if (flowError) return "exception";
  if (rowMissing(row, company)) return "manual";

  const parsed = task.naming_parsed_fields;
  const category = suggestNamingCategory(parsed, categories);
  const unsafeAiField = Boolean(
    parsed &&
    ((parsed.missing_fields?.length ?? 0) > 0 || (parsed.inferred_fields?.length ?? 0) > 0),
  );
  const differsFromSafeAi =
    row.subject.trim() !== sourceSubject(task) ||
    row.category_id !== category?.id ||
    row.formed_on !== parsedValue(task, "date") ||
    row.version.toUpperCase() !== parsedValue(task, "version");
  if (
    !parsed ||
    unsafeAiField ||
    category?.basis !== "ai" ||
    differsFromSafeAi ||
    (company && !row.applicable_to)
  ) {
    return "manual";
  }
  return "ai_ready";
}

export default function PendingBatchActions({
  tasks,
  flow,
}: {
  tasks: PendingIngestItemDTO[];
  flow: UploadFlow;
}) {
  const [rejectOpen, setRejectOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [stage, setStage] = useState<"target" | "review">("target");
  const [targetLibrary, setTargetLibrary] = useState<TargetLibrary>("");
  const [targetProjectId, setTargetProjectId] = useState("");
  const [options, setOptions] = useState<NamingOptionsDTO | null>(null);
  const [rows, setRows] = useState<ReviewRows>({});
  const [previews, setPreviews] = useState<PreviewRows>({});
  const [reviewTargetKey, setReviewTargetKey] = useState("");
  const [loading, setLoading] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [reviewFilter, setReviewFilter] = useState<ReviewFilter>("all");
  const [deleteCandidate, setDeleteCandidate] = useState<PendingIngestItemDTO | null>(null);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [deleteFeedback, setDeleteFeedback] = useState<Record<string, DeleteFeedback>>({});

  const selectedConfirmTasks = tasks.filter(
    (task) => flow.batchSelection.includes(task.id) && task.can_batch_confirm,
  );
  const selectedRejectTasks = tasks.filter(
    (task) => flow.batchSelection.includes(task.id) && task.can_batch_reject,
  );
  const company = targetLibrary === "company";
  const categories = useMemo(() => options?.categories ?? [], [options]);
  const reviewed = selectedConfirmTasks.filter((task) => previews[task.id]?.submittable).length;
  const missingDates = selectedConfirmTasks.filter(
    (task) => !DATE_PATTERN.test(rows[task.id]?.formed_on ?? ""),
  ).length;
  const allPreviewed =
    stage === "review" &&
    selectedConfirmTasks.length > 0 &&
    selectedConfirmTasks.every(
      (task) => !rowMissing(rows[task.id], company) && previews[task.id]?.submittable,
    );
  const targetReady =
    Boolean(targetLibrary) && (targetLibrary !== "project" || Boolean(targetProjectId));

  const targetKey = `${targetLibrary}:${targetProjectId}`;
  const statesByTask = useMemo(
    () =>
      Object.fromEntries(
        selectedConfirmTasks.flatMap((task) => {
          const row = rows[task.id];
          if (!row) return [];
          return [
            [
              task.id,
              reviewState(
                task,
                row,
                previews[task.id],
                categories,
                company,
                flow.batchErrors[task.id],
              ),
            ],
          ];
        }),
      ) as Record<string, ReviewState>,
    [categories, company, flow.batchErrors, previews, rows, selectedConfirmTasks],
  );
  const stateCounts = useMemo(
    () => ({
      all: selectedConfirmTasks.length,
      ai_ready: selectedConfirmTasks.filter((task) => statesByTask[task.id] === "ai_ready").length,
      manual: selectedConfirmTasks.filter((task) => statesByTask[task.id] === "manual").length,
      reviewed: selectedConfirmTasks.filter((task) => statesByTask[task.id] === "reviewed").length,
      exception: selectedConfirmTasks.filter((task) => statesByTask[task.id] === "exception")
        .length,
    }),
    [selectedConfirmTasks, statesByTask],
  );
  const visibleConfirmTasks = selectedConfirmTasks.filter(
    (task) => reviewFilter === "all" || statesByTask[task.id] === reviewFilter,
  );
  const previewSummary = useMemo(
    () =>
      `已核对 ${reviewed}/${selectedConfirmTasks.length} 条，仍有 ${missingDates} 条需补充形成日期`,
    [missingDates, reviewed, selectedConfirmTasks.length],
  );

  if (selectedConfirmTasks.length === 0 && selectedRejectTasks.length === 0) return null;

  const updateRow = (taskId: string, patch: Partial<BatchNamingValuesDTO>) => {
    setRows((current) => ({ ...current, [taskId]: { ...current[taskId], ...patch } }));
    setPreviews((current) => {
      const next = { ...current };
      delete next[taskId];
      return next;
    });
  };

  const confirmSingleDelete = async () => {
    const task = deleteCandidate;
    if (!task) return;
    setDeletingTaskId(task.id);
    const result = await flow.handleDeleteBatchReviewItem(task.id);
    setDeletingTaskId(null);
    setDeleteCandidate(null);
    if (!result.ok) {
      setDeleteFeedback((current) => ({
        ...current,
        [task.id]: { message: result.message, retryable: result.retryable },
      }));
      return;
    }
    setRows((current) => {
      const next = { ...current };
      delete next[task.id];
      return next;
    });
    setPreviews((current) => {
      const next = { ...current };
      delete next[task.id];
      return next;
    });
    setDeleteFeedback((current) => {
      const next = { ...current };
      delete next[task.id];
      return next;
    });
  };

  const advanceTarget = async () => {
    if (!targetReady) return;
    if (targetLibrary === "personal") {
      setConfirmOpen(false);
      void flow.handleBatchConfirm(selectedConfirmTasks, "personal", undefined);
      return;
    }
    if (targetLibrary !== "project" && targetLibrary !== "company") return;
    const destination = targetLibrary;
    setLoading(true);
    setDialogError(null);
    try {
      const value = await fetchNamingOptions(destination, targetProjectId || undefined);
      if (!value.required) {
        setConfirmOpen(false);
        void flow.handleBatchConfirm(
          selectedConfirmTasks,
          destination,
          targetProjectId || undefined,
        );
        return;
      }
      setOptions(value);
      if (reviewTargetKey !== targetKey) {
        setRows(initialRows(selectedConfirmTasks, value));
        setPreviews({});
        setReviewTargetKey(targetKey);
      }
      setStage("review");
    } catch (error) {
      setDialogError(error instanceof ApiError ? error.message : "命名规则暂时无法加载");
    } finally {
      setLoading(false);
    }
  };

  const refreshPreviews = async () => {
    if (targetLibrary !== "project" && targetLibrary !== "company") return;
    setLoading(true);
    setDialogError(null);
    try {
      const response = await previewBatchIngestNaming({
        targetScope: targetLibrary,
        targetProjectId: targetProjectId || undefined,
        items: selectedConfirmTasks.map((task) => ({ taskId: task.id, naming: rows[task.id] })),
      });
      const next = Object.fromEntries(response.items.map((item) => [item.task_id, item]));
      setPreviews(next);
      setRows((current) => {
        const updated = { ...current };
        response.items.forEach((item) => {
          const subject = item.fields?.subject;
          if (typeof subject === "string" && updated[item.task_id]) {
            updated[item.task_id] = { ...updated[item.task_id], subject };
          }
        });
        return updated;
      });
    } catch (error) {
      setDialogError(
        error instanceof ApiError ? error.message : "批量预览暂时失败，资料仍保留，可稍后重试",
      );
    } finally {
      setLoading(false);
    }
  };

  const submitGovernedBatch = () => {
    if (!allPreviewed || (targetLibrary !== "project" && targetLibrary !== "company")) return;
    setConfirmOpen(false);
    // Keep user edits for failed rows, but require a fresh server preview after
    // any final submission because policy or membership may have changed.
    setPreviews({});
    void flow.handleBatchConfirm(
      selectedConfirmTasks,
      targetLibrary,
      targetProjectId || undefined,
      Object.fromEntries(selectedConfirmTasks.map((task) => [task.id, rows[task.id]])),
    );
  };

  return (
    <>
      <div className="upload77-batch-actions">
        {selectedConfirmTasks.length > 0 && (
          <button
            className="btn-primary"
            disabled={flow.batchBusy}
            onClick={() => {
              setStage("target");
              setReviewFilter("all");
              setTargetLibrary("");
              setTargetProjectId("");
              setDialogError(null);
              setConfirmOpen(true);
            }}
            type="button"
          >
            {flow.batchBusy && flow.batchOperation === "confirm"
              ? "正在逐条确认"
              : `批量确认入库（${selectedConfirmTasks.length}）`}
          </button>
        )}
        {selectedRejectTasks.length > 0 && (
          <button
            className="btn-secondary upload77-batch-reject"
            disabled={flow.batchBusy}
            onClick={() => setRejectOpen(true)}
            type="button"
          >
            批量拒绝入库（{selectedRejectTasks.length}）
          </button>
        )}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title={
          stage === "target"
            ? `确认入库 ${selectedConfirmTasks.length} 项资料`
            : `逐条核对 ${selectedConfirmTasks.length} 项规范命名`
        }
        description={
          stage === "target"
            ? "请选择一个明确的目标知识库；取消不会创建资产或改变任务状态。"
            : undefined
        }
        confirmText={
          stage === "review" || targetLibrary === "personal" || !targetLibrary
            ? "确认批量入库"
            : "下一步：核对命名"
        }
        busyText={stage === "target" ? "正在加载规则" : "正在核对"}
        busy={loading}
        confirmDisabled={stage === "target" ? !targetReady : !allPreviewed}
        error={dialogError}
        errorDescription={dialogError}
        panelClassName={stage === "review" ? "upload77-batch-naming-dialog" : undefined}
        onCancel={() => setConfirmOpen(false)}
        onConfirm={stage === "target" ? () => void advanceTarget() : submitGovernedBatch}
      >
        {stage === "target" ? (
          <>
            <label className="upload77-field">
              <span>目标知识库</span>
              <select
                aria-label="批量入库目标知识库"
                value={targetLibrary}
                onChange={(event) => {
                  setTargetLibrary(event.target.value as TargetLibrary);
                  setTargetProjectId("");
                }}
              >
                <option value="">请选择目标知识库</option>
                <option value="personal">个人知识库</option>
                {(flow.projects ?? []).length > 0 && <option value="project">项目知识库</option>}
                {flow.canUseCompanyTarget && <option value="company">公司知识库</option>}
              </select>
            </label>
            {targetLibrary === "project" && (
              <label className="upload77-field">
                <span>具体项目</span>
                <select
                  aria-label="批量入库目标项目"
                  value={targetProjectId}
                  onChange={(event) => setTargetProjectId(event.target.value)}
                >
                  <option value="">请选择目标项目</option>
                  {(flow.projects ?? []).map((project) => (
                    <option key={project.projectId} value={project.projectId}>
                      {project.projectName}
                    </option>
                  ))}
                </select>
              </label>
            )}
          </>
        ) : (
          <div className="upload77-batch-naming-review">
            <div className="upload77-batch-naming-toolbar">
              <div>
                <span role="status">{previewSummary}</span>
                <span className="upload77-batch-filter-summary" role="status">
                  当前筛选显示 {visibleConfirmTasks.length}/{selectedConfirmTasks.length} 条
                </span>
              </div>
              <button
                className="btn-secondary"
                disabled={loading}
                onClick={() => void refreshPreviews()}
                type="button"
              >
                生成或刷新全部预览
              </button>
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
                  onClick={() => setReviewFilter(value)}
                  type="button"
                >
                  {label}（{stateCounts[value]}）
                </button>
              ))}
            </div>
            <div className="upload77-batch-naming-scroll">
              {visibleConfirmTasks.length === 0 && (
                <div className="upload77-batch-filter-empty" role="status">
                  当前筛选下没有资料
                </div>
              )}
              {visibleConfirmTasks.map((task) => {
                const row = rows[task.id];
                const preview = previews[task.id];
                if (!row) return null;
                const localError = rowMissing(row, company);
                const serverError = previewError(preview);
                const fieldError = localError ?? serverError;
                const categorySuggestion = suggestNamingCategory(
                  task.naming_parsed_fields,
                  categories,
                );
                return (
                  <article className="upload77-batch-naming-row" key={task.id}>
                    <header>
                      <strong title={task.source_file_name}>
                        {selectedConfirmTasks.indexOf(task) + 1}. {task.source_file_name}
                      </strong>
                      <div className="upload77-batch-naming-row-actions">
                        <span>{preview?.submittable ? "已核对" : "待核对"}</span>
                        <button
                          aria-label={`删除 ${task.source_file_name}`}
                          className="upload77-batch-delete"
                          disabled={!task.can_batch_reject || deletingTaskId === task.id}
                          onClick={() => {
                            setDeleteFeedback((current) => {
                              const next = { ...current };
                              delete next[task.id];
                              return next;
                            });
                            setDeleteCandidate(task);
                          }}
                          title={
                            task.can_batch_reject ? "永久删除错误上传资料" : "当前资料不能永久删除"
                          }
                          type="button"
                        >
                          <Trash2 aria-hidden="true" size={14} />
                          删除
                        </button>
                      </div>
                    </header>
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
                          <small className="upload77-batch-naming-error">
                            {fieldError.message}
                          </small>
                        )}
                      </label>
                      <label>
                        <span>目录类别</span>
                        <select
                          aria-label={`${task.source_file_name} 目录类别`}
                          value={row.category_id}
                          onChange={(event) =>
                            updateRow(task.id, { category_id: event.target.value })
                          }
                        >
                          <option value="">请选择</option>
                          {categories.map((category) => (
                            <option key={category.id} value={category.id}>
                              {category.primary} / {category.secondary}
                            </option>
                          ))}
                        </select>
                        {fieldError?.field === "category_id" && (
                          <small className="upload77-batch-naming-error">
                            {fieldError.message}
                          </small>
                        )}
                        {categorySuggestion?.basis === "ai" &&
                          categorySuggestion.id === row.category_id && (
                            <small className="upload77-batch-naming-notice">
                              已按 AI 建议预选，可人工修改
                            </small>
                          )}
                      </label>
                      <label>
                        <span>文件形成日期</span>
                        <input
                          aria-label={`${task.source_file_name} 文件形成日期`}
                          type="date"
                          value={row.formed_on}
                          onChange={(event) =>
                            updateRow(task.id, { formed_on: event.target.value })
                          }
                        />
                        {fieldError?.field === "formed_on" && (
                          <small className="upload77-batch-naming-error">
                            {fieldError.message}
                          </small>
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
                          <small className="upload77-batch-naming-error">
                            {fieldError.message}
                          </small>
                        )}
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
                            <small className="upload77-batch-naming-error">
                              {fieldError.message}
                            </small>
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
                      </label>
                    </div>
                    <div
                      className="upload77-batch-naming-preview"
                      title={preview?.canonical_name ?? undefined}
                    >
                      <strong>规范名预览：</strong>
                      {preview?.canonical_name ?? "尚未生成"}
                    </div>
                    {!localError && !preview && (
                      <div className="upload77-batch-naming-notice">请生成预览</div>
                    )}
                    {serverError?.field === null && (
                      <div className="upload77-batch-naming-error">{serverError.message}</div>
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
        )}
      </ConfirmDialog>

      <ConfirmDialog
        open={deleteCandidate !== null}
        title="永久删除这条错误上传资料？"
        description="确认后将永久删除该错误上传资料，不会创建知识资产，操作不可恢复。"
        confirmText="确认永久删除"
        busyText="正在永久删除"
        busy={deletingTaskId !== null}
        danger
        onCancel={() => setDeleteCandidate(null)}
        onConfirm={() => void confirmSingleDelete()}
      />

      <ConfirmDialog
        open={rejectOpen}
        title={`永久拒绝选中的 ${selectedRejectTasks.length} 条待确认任务？`}
        description={`确认后将严格逐条删除这 ${selectedRejectTasks.length} 条待确认任务，操作不可恢复，且不会创建知识资产。`}
        confirmText="确认永久拒绝"
        busyText="正在逐条拒绝"
        busy={flow.batchBusy && flow.batchOperation === "reject"}
        danger
        onCancel={() => setRejectOpen(false)}
        onConfirm={() => {
          setRejectOpen(false);
          void flow.handleBatchReject(selectedRejectTasks);
        }}
      />
    </>
  );
}
