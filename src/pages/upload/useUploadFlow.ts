import { useState, useRef, useCallback, useEffect } from "react";
import { ApiError, createClientUuid } from "../../api/http";
import { fetchAuthMe } from "../../api/auth";
import {
  confirmIngest,
  createIngestUpload,
  createUploadSession,
  deletePendingTask,
  fetchIngestAiResult,
  fetchIngestTaskStatus,
  fetchPendingIngestTasks,
  fetchUploadSession,
  fetchUploadSessions,
  removeFailedUploadSessionItems,
  removeUploadSessionItem,
  retryUploadSessionItem,
} from "../../api/ingest";
import type {
  IngestAiResultDTO,
  NamingFields,
  PendingIngestItemDTO,
  UploadSessionDTO,
} from "../../types/ingest";
import { useModelSelection } from "../../hooks/useModelSelection";
import {
  POLL_INTERVAL_MS,
  POLL_MAX_ATTEMPTS,
  sleep,
  visibilityToKey,
  type FlowState,
  type PathBranch,
  type TargetLibrary,
} from "./uploadConstants";
import {
  isMacosMetadataPath,
  MACOS_METADATA_MESSAGE,
  readDroppedFiles,
  safeRejectedDisplayName,
  UNREADABLE_FILE_MESSAGE,
  type DroppedFileCandidate,
} from "./folderDrop";

export type LocalUploadQueueState =
  | "queued"
  | "uploading"
  | "processing"
  | "awaiting_confirmation"
  | "completed"
  | "cancelled"
  | "failed";

export interface LocalUploadQueueItem {
  id: string;
  file: File | null;
  fileName: string;
  fileSize: number;
  fileType: string;
  status: LocalUploadQueueState;
  error: string | null;
  ingestTaskId: string | null;
  pollAttempts: number;
  batchNumber?: number;
  sameNameWarning?: boolean;
  retryable?: boolean;
}

type IntakeRejectionCode =
  | "file_unreadable"
  | "file_read_timeout"
  | "macos_metadata"
  | "unsupported_file_type"
  | "file_too_large";

export interface UploadIntakeFeedback {
  kind: "checking" | "accepted" | "partial" | "rejected" | "network_error" | "cancelled";
  total: number;
  accepted: number;
  rejected: number;
  waitingBatches: number;
  batchSizes: number[];
  message: string;
}

const LOCAL_UPLOAD_MAX_BYTES = 25 * 1024 * 1024;
const LOCAL_UPLOAD_EXTENSIONS = new Set([
  "md",
  "markdown",
  "txt",
  "pdf",
  "doc",
  "docx",
  "ppt",
  "pptx",
  "xls",
  "xlsx",
]);

function localFileError(file: File): { code: IntakeRejectionCode; message: string } | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!LOCAL_UPLOAD_EXTENSIONS.has(extension)) {
    return { code: "unsupported_file_type", message: "该文件类型暂不支持上传" };
  }
  if (file.size > LOCAL_UPLOAD_MAX_BYTES) {
    return { code: "file_too_large", message: "文件超过 25 MiB 大小上限" };
  }
  return null;
}

function batchSizes(total: number): number[] {
  return Array.from({ length: Math.ceil(total / 200) }, (_, index) =>
    Math.min(200, total - index * 200),
  );
}

async function probeReadableFile(
  file: File,
): Promise<{ code: IntakeRejectionCode; message: string } | null> {
  if (file.size === 0) return null;
  const probe = file.slice(0, 1);
  if (typeof probe.arrayBuffer !== "function") return null;
  let timeoutId: ReturnType<typeof window.setTimeout> | undefined;
  try {
    await Promise.race([
      probe.arrayBuffer(),
      new Promise<never>((_, reject) => {
        timeoutId = window.setTimeout(() => reject(new Error("file_read_timeout")), 5000);
      }),
    ]);
    return null;
  } catch (error) {
    return {
      code:
        error instanceof Error && error.message === "file_read_timeout"
          ? "file_read_timeout"
          : "file_unreadable",
      message: UNREADABLE_FILE_MESSAGE,
    };
  } finally {
    if (timeoutId) window.clearTimeout(timeoutId);
  }
}

// 资产化确认工作台的容器 Hook：收拢企业微信待确认 / 本地上传共享的
// 全部状态、AI 结果轮询、人工校正字段、确认入库与重置逻辑。页面本体只消费此 hook、
// 做步骤路由与顶层 state 传递；展示拆到 UploadStepA / UploadStepB / UploadConfirmPanel。
export function useUploadFlow() {
  const [activePath, setActivePath] = useState<PathBranch>("b");

  // PBC-38：入库模型选择（默认平台推荐 embedding/rerank；缺默认时禁用提交）。
  const models = useModelSelection();

  // Path B local upload state
  const [flowState, setFlowState] = useState<FlowState>("idle");
  const [fileName, setFileName] = useState("");
  const [fileSize, setFileSize] = useState(0);
  const [fileType, setFileType] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [localUploadQueue, setLocalUploadQueue] = useState<LocalUploadQueueItem[]>([]);
  const [uploadSession, setUploadSession] = useState<UploadSessionDTO | null>(null);
  const localUploadQueueRef = useRef<LocalUploadQueueItem[]>([]);
  const localUploadWorkerRef = useRef(false);
  const localStatusPollingRef = useRef(false);
  const localStatusPollRunRef = useRef(0);
  const localUploadSequenceRef = useRef(0);
  const directoryReadRunRef = useRef(0);
  const [folderDropNotice, setFolderDropNotice] = useState<string | null>(null);
  const [intakeFeedback, setIntakeFeedback] = useState<UploadIntakeFeedback | null>(null);
  const [extraction, setExtraction] = useState<{
    status: string | null;
    charCount: number | null;
    isDuplicate: boolean;
  } | null>(null);
  const [naming, setNaming] = useState<NamingFields | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const workflowRunRef = useRef(0);
  const pendingRequestRef = useRef(0);
  const localPendingRequestRef = useRef(0);

  const beginWorkflowRun = useCallback(() => {
    workflowRunRef.current += 1;
    return workflowRunRef.current;
  }, []);
  const isCurrentWorkflowRun = useCallback((runId: number) => workflowRunRef.current === runId, []);

  // Path A：企微微盘待确认任务。
  const [pendingTasks, setPendingTasks] = useState<PendingIngestItemDTO[]>([]);
  // Path A is lazy-mounted. Start in loading state so the first switch cannot
  // flash an empty result before its effect begins the pending-task request.
  const [pendingLoading, setPendingLoading] = useState(true);
  const [pendingError, setPendingError] = useState<string | null>(null);
  const [selectedTaskName, setSelectedTaskName] = useState("");

  // Path B：本地上传待确认任务（历史上传未确认的，展示在拖放区下方）。
  const [localPendingTasks, setLocalPendingTasks] = useState<PendingIngestItemDTO[]>([]);
  const [localPendingLoading, setLocalPendingLoading] = useState(true);
  const [localPendingError, setLocalPendingError] = useState<string | null>(null);
  const [batchSelection, setBatchSelection] = useState<string[]>([]);
  const [batchStatus, setBatchStatus] = useState<
    Record<string, "waiting" | "processing" | "success" | "failed">
  >({});
  const [batchBusy, setBatchBusy] = useState(false);
  const [batchOperation, setBatchOperation] = useState<"confirm" | "reject" | null>(null);
  const [batchErrors, setBatchErrors] = useState<Record<string, string>>({});
  const batchRunRef = useRef<number | null>(null);

  // Shared confirmation fields
  const [editTitle, setEditTitle] = useState("");
  const [editOneLiner, setEditOneLiner] = useState("");
  const [editSummary, setEditSummary] = useState("");
  const [editKeyPoints, setEditKeyPoints] = useState("");
  const [llmStatus, setLlmStatus] = useState<{
    status: string | null;
    provider: string | null;
    summaryStatus: IngestAiResultDTO["summary_status"];
    generationModelRef: string | null;
  } | null>(null);
  const [desensitization, setDesensitization] = useState<{
    status: string | null;
    counts: Record<string, number> | null;
    message: string | null;
  } | null>(null);
  const [editTags, setEditTags] = useState("");
  const [editVisibility, setEditVisibility] = useState("项目内");
  const [editBizStage, setEditBizStage] = useState("行动辅导");
  const [targetLibrary, setTargetLibrary] = useState<TargetLibrary>("personal");
  const [confirmConfidence, setConfirmConfidence] = useState("—");

  // 真实入库任务状态
  const [taskId, setTaskId] = useState<string | null>(null);
  const [resultAssetId, setResultAssetId] = useState<string | null>(null);
  const [submitReviewId, setSubmitReviewId] = useState<string | null>(null);
  const [submitIndexStatus, setSubmitIndexStatus] = useState<string | null>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [processingNote, setProcessingNote] = useState<string | null>(null);
  const [editAssetType, setEditAssetType] = useState("methodology");
  const [editConfidentiality, setEditConfidentiality] = useState("L2");
  const [editAiAccess, setEditAiAccess] = useState("A2");
  const [projects, setProjects] = useState<{ projectId: string; projectName: string }[]>([]);
  const [targetProjectId, setTargetProjectId] = useState("");

  useEffect(() => {
    return () => {
      workflowRunRef.current += 1;
      batchRunRef.current = null;
      pendingRequestRef.current += 1;
      localPendingRequestRef.current += 1;
      localStatusPollRunRef.current += 1;
      directoryReadRunRef.current += 1;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  useEffect(() => {
    fetchAuthMe()
      .then((me) => {
        setProjects(
          me.projects.map((p) => ({ projectId: p.projectId, projectName: p.projectName })),
        );
        if (me.projects.length > 0) setTargetProjectId(me.projects[0].projectId);
      })
      .catch(() => setProjects([]));
  }, []);

  // 待确认入库：拉取当前用户可处理的全部待确认任务（不再按来源过滤）。
  const loadPending = useCallback(async () => {
    const requestId = ++pendingRequestRef.current;
    setPendingLoading(true);
    setPendingError(null);
    try {
      const tasks = await fetchPendingIngestTasks("path_a_wecom");
      if (pendingRequestRef.current !== requestId) return;
      setPendingTasks(tasks);
      setBatchSelection((selected) =>
        selected.filter((id) =>
          tasks.some((task) => task.id === id && task.status === "pending_confirmation"),
        ),
      );
    } catch (e) {
      if (pendingRequestRef.current !== requestId) return;
      setPendingError(e instanceof ApiError ? e.message : "待确认任务暂时无法加载，请稍后重试");
    } finally {
      if (pendingRequestRef.current === requestId) setPendingLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activePath === "a") void loadPending();
  }, [activePath, loadPending]);

  // 本地上传待确认任务（Path B 专属，按来源过滤到 path_b_upload）。
  const loadLocalPending = useCallback(async () => {
    const requestId = ++localPendingRequestRef.current;
    setLocalPendingLoading(true);
    setLocalPendingError(null);
    try {
      const tasks = await fetchPendingIngestTasks("path_b_upload");
      if (localPendingRequestRef.current !== requestId) return;
      setLocalPendingTasks(tasks);
      setBatchSelection((selected) =>
        selected.filter((id) =>
          tasks.some((task) => task.id === id && task.status === "pending_confirmation"),
        ),
      );
    } catch (e) {
      if (localPendingRequestRef.current !== requestId) return;
      setLocalPendingError(
        e instanceof ApiError ? e.message : "待确认任务暂时无法加载，请稍后重试",
      );
    } finally {
      if (localPendingRequestRef.current === requestId) setLocalPendingLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activePath === "b") void loadLocalPending();
  }, [activePath, loadLocalPending]);

  const updateLocalUploadQueue = useCallback(
    (update: (items: LocalUploadQueueItem[]) => LocalUploadQueueItem[]) => {
      const next = update(localUploadQueueRef.current);
      localUploadQueueRef.current = next;
      setLocalUploadQueue(next);
    },
    [],
  );

  const applyUploadSession = useCallback((value: UploadSessionDTO) => {
    setUploadSession(value);
    const next: LocalUploadQueueItem[] = value.items.map((item) => ({
      id: item.id,
      file: null,
      fileName: item.file_name,
      fileSize: item.file_size,
      fileType: item.file_type || item.file_name.split(".").pop()?.toUpperCase() || "未知",
      status: item.status === "waiting" ? "queued" : item.status,
      error: item.error_message,
      ingestTaskId: null,
      pollAttempts: 0,
      batchNumber: item.batch_number,
      sameNameWarning: item.same_name_warning,
      retryable: item.retryable,
    }));
    localUploadQueueRef.current = next;
    setLocalUploadQueue(next);
    const accepted = value.completed_files + value.processing_files + value.waiting_files;
    const sizes = batchSizes(value.total_files);
    const kind =
      accepted === 0 && value.failed_files > 0
        ? "rejected"
        : value.failed_files > 0
          ? "partial"
          : "accepted";
    setIntakeFeedback({
      kind,
      total: value.total_files,
      accepted,
      rejected: value.failed_files,
      waitingBatches: value.waiting_files > 0 ? Math.ceil(value.waiting_files / 200) : 0,
      batchSizes: sizes,
      message:
        value.items.length === 0 && value.total_files > 0
          ? "失败项已清理；本次队列当前无可处理项目。"
          : kind === "rejected"
            ? "本次文件全部被安全门禁拒绝，请按每项原因处理后重新选择。"
            : kind === "partial"
              ? "本次文件已接收，部分项目被拒绝；队列中的逐项状态为最终依据。"
              : value.total_files > 200
                ? `全部已接收，后续批次将自动等待（${sizes.join(" + ")}）。`
                : "文件已接收并进入本次上传队列。",
    });
  }, []);

  useEffect(() => {
    if (activePath !== "b") return;
    if (typeof fetchUploadSessions !== "function") return;
    let active = true;
    void fetchUploadSessions()
      .then((sessions) => {
        if (active && sessions[0]) applyUploadSession(sessions[0]);
      })
      .catch(() => {
        // The existing pending list remains available if session recovery is temporarily offline.
      });
    return () => {
      active = false;
    };
  }, [activePath, applyUploadSession]);

  useEffect(() => {
    if (
      activePath !== "b" ||
      !uploadSession ||
      !uploadSession.items.some((item) =>
        ["waiting", "uploading", "processing"].includes(item.status),
      )
    ) {
      return;
    }
    let active = true;
    let inFlight = false;
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const next = await fetchUploadSession(uploadSession.id);
        if (!active) return;
        applyUploadSession(next);
        if (next.completed_files > uploadSession.completed_files) void loadLocalPending();
      } catch {
        // Keep the last server-confirmed states; a later poll can recover.
      } finally {
        inFlight = false;
      }
    };
    const timer = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => {
      active = false;
      window.clearInterval(timer);
    };
  }, [activePath, applyUploadSession, loadLocalPending, uploadSession]);

  const removeLocalTaskEverywhere = useCallback(
    (ingestTaskId: string) => {
      setLocalPendingTasks((items) => items.filter((item) => item.id !== ingestTaskId));
      updateLocalUploadQueue((items) => items.filter((item) => item.ingestTaskId !== ingestTaskId));
    },
    [updateLocalUploadQueue],
  );

  const processLocalUploadQueue = useCallback(async () => {
    if (localUploadWorkerRef.current) return;
    localUploadWorkerRef.current = true;
    try {
      while (true) {
        const item = localUploadQueueRef.current.find((candidate) => candidate.status === "queued");
        if (!item) break;
        updateLocalUploadQueue((items) =>
          items.map((candidate) =>
            candidate.id === item.id
              ? { ...candidate, status: "uploading", error: null }
              : candidate,
          ),
        );
        try {
          if (!item.file) throw new Error("源文件不可用，请重新选择文件");
          const upload = await createIngestUpload({ file: item.file });
          updateLocalUploadQueue((items) =>
            items.map((candidate) =>
              candidate.id === item.id
                ? {
                    ...candidate,
                    ingestTaskId: upload.ingest_task_id,
                    pollAttempts: 0,
                    status: "processing",
                    error: null,
                  }
                : candidate,
            ),
          );
        } catch (error) {
          updateLocalUploadQueue((items) =>
            items.map((candidate) =>
              candidate.id === item.id
                ? {
                    ...candidate,
                    status: "failed",
                    error: error instanceof ApiError ? error.message : "上传失败，请稍后重试",
                  }
                : candidate,
            ),
          );
        }
      }
    } finally {
      localUploadWorkerRef.current = false;
    }
  }, [updateLocalUploadQueue]);

  const reconcileLocalUploadQueue = useCallback(async () => {
    if (localStatusPollingRef.current) return;
    const runId = localStatusPollRunRef.current;
    const processing = localUploadQueueRef.current.filter(
      (item) => item.status === "processing" && item.ingestTaskId,
    );
    if (!processing.length) return;
    localStatusPollingRef.current = true;
    try {
      let refreshPending = false;
      for (const item of processing) {
        if (localStatusPollRunRef.current !== runId) return;
        try {
          const status = await fetchIngestTaskStatus(item.ingestTaskId!);
          if (localStatusPollRunRef.current !== runId) return;
          const current = localUploadQueueRef.current.find(
            (candidate) =>
              candidate.id === item.id &&
              candidate.status === "processing" &&
              candidate.ingestTaskId === item.ingestTaskId,
          );
          if (!current) continue;
          const pollAttempts = current.pollAttempts + 1;
          const failed = status.status === "failed" || status.stage === "failed";
          const readyForConfirmation =
            status.stage === "awaiting_confirmation" ||
            status.next_action?.key === "review_and_confirm";
          if (failed) {
            updateLocalUploadQueue((items) =>
              items.map((candidate) =>
                candidate.id === item.id
                  ? {
                      ...candidate,
                      pollAttempts,
                      status: "failed",
                      error: status.error?.message ?? "文件处理失败，请检查文件后重试",
                    }
                  : candidate,
              ),
            );
          } else if (readyForConfirmation) {
            refreshPending = true;
            updateLocalUploadQueue((items) =>
              items.map((candidate) =>
                candidate.id === item.id
                  ? {
                      ...candidate,
                      pollAttempts,
                      status: "awaiting_confirmation",
                      error:
                        status.status === "degraded"
                          ? (status.error?.message ?? "文件已完成安全降级处理，请核对后确认入库")
                          : null,
                    }
                  : candidate,
              ),
            );
          } else if (pollAttempts >= POLL_MAX_ATTEMPTS) {
            updateLocalUploadQueue((items) =>
              items.map((candidate) =>
                candidate.id === item.id
                  ? {
                      ...candidate,
                      pollAttempts,
                      status: "failed",
                      error: "文件处理超时，请稍后重试",
                    }
                  : candidate,
              ),
            );
          } else {
            updateLocalUploadQueue((items) =>
              items.map((candidate) =>
                candidate.id === item.id ? { ...candidate, pollAttempts } : candidate,
              ),
            );
          }
        } catch {
          if (localStatusPollRunRef.current !== runId) return;
          updateLocalUploadQueue((items) =>
            items.map((candidate) => {
              if (
                candidate.id !== item.id ||
                candidate.status !== "processing" ||
                candidate.ingestTaskId !== item.ingestTaskId
              ) {
                return candidate;
              }
              const pollAttempts = candidate.pollAttempts + 1;
              return pollAttempts >= POLL_MAX_ATTEMPTS
                ? {
                    ...candidate,
                    pollAttempts,
                    status: "failed",
                    error: "文件状态暂时无法同步，请稍后重试",
                  }
                : { ...candidate, pollAttempts };
            }),
          );
        }
      }
      if (refreshPending && localStatusPollRunRef.current === runId) void loadLocalPending();
    } finally {
      localStatusPollingRef.current = false;
    }
  }, [loadLocalPending, updateLocalUploadQueue]);

  const hasLocalProcessing = localUploadQueue.some((item) => item.status === "processing");

  useEffect(() => {
    if (activePath !== "b" || !hasLocalProcessing) {
      return;
    }
    const runId = ++localStatusPollRunRef.current;
    void reconcileLocalUploadQueue();
    const timer = window.setInterval(() => void reconcileLocalUploadQueue(), POLL_INTERVAL_MS);
    return () => {
      window.clearInterval(timer);
      if (localStatusPollRunRef.current === runId) localStatusPollRunRef.current += 1;
    };
  }, [activePath, hasLocalProcessing, reconcileLocalUploadQueue]);

  const enqueueLocalFiles = useCallback(
    async (files: Iterable<File | DroppedFileCandidate>) => {
      const source = Array.from(files);
      if (!source.length) {
        setIntakeFeedback({
          kind: "cancelled",
          total: 0,
          accepted: 0,
          rejected: 0,
          waitingBatches: 0,
          batchSizes: [],
          message: "未选择文件，本次操作已取消。",
        });
        return;
      }
      setIntakeFeedback({
        kind: "checking",
        total: source.length,
        accepted: 0,
        rejected: 0,
        waitingBatches: 0,
        batchSizes: batchSizes(source.length),
        message: `正在逐项检查 ${source.length} 个文件的可读性与上传条件…`,
      });
      const prepared = await Promise.all(
        source.map(async (input) => {
          const candidate =
            input instanceof File ? { file: input, displayName: input.name } : input;
          const metadata = isMacosMetadataPath(candidate.displayName)
            ? { code: "macos_metadata" as const, message: MACOS_METADATA_MESSAGE }
            : null;
          const declaredUnreadable = candidate.readError
            ? { code: "file_unreadable" as const, message: UNREADABLE_FILE_MESSAGE }
            : null;
          const localGate = localFileError(candidate.file);
          const rejection =
            metadata ??
            declaredUnreadable ??
            localGate ??
            (await probeReadableFile(candidate.file));
          return { candidate, rejection };
        }),
      );
      const items = prepared.map(({ candidate, rejection }) => {
        return {
          id: `local-upload-${++localUploadSequenceRef.current}`,
          file: candidate.file,
          fileName: candidate.file.name,
          fileSize: candidate.file.size,
          fileType:
            candidate.file.name.split(".").pop()?.toUpperCase() || candidate.file.type || "未知",
          status: rejection ? "failed" : "queued",
          error: rejection?.message ?? null,
          ingestTaskId: null,
          pollAttempts: 0,
        } satisfies LocalUploadQueueItem;
      });
      updateLocalUploadQueue((current) => [...current, ...items]);
      const rejected = prepared.filter((item) => item.rejection);
      const accepted = prepared.length - rejected.length;
      const sizes = batchSizes(prepared.length);
      setIntakeFeedback({
        kind: accepted === 0 ? "rejected" : rejected.length > 0 ? "partial" : "accepted",
        total: prepared.length,
        accepted,
        rejected: rejected.length,
        waitingBatches: Math.max(0, sizes.length - 1),
        batchSizes: sizes,
        message:
          accepted === 0
            ? "本次文件全部被安全门禁拒绝，请按每项原因处理后重新选择。"
            : rejected.length > 0
              ? `已接收 ${accepted} 项，拒绝 ${rejected.length} 项；详细原因已保留在队列中。`
              : prepared.length > 200
                ? `全部已接收，后续批次将自动等待（${sizes.join(" + ")}）。`
                : `已接收 ${accepted} 项，正在创建上传队列。`,
      });
      if (typeof createUploadSession !== "function") {
        void processLocalUploadQueue();
        return;
      }
      const uploadFiles = prepared
        .filter((item) => !item.rejection)
        .map((item) => item.candidate.file);
      const rejectedFiles = prepared.flatMap(({ candidate, rejection }) =>
        rejection
          ? [
              {
                file_name:
                  rejection.code === "macos_metadata"
                    ? safeRejectedDisplayName(candidate.displayName)
                    : candidate.file.name,
                file_size: candidate.file.size,
                file_type: candidate.file.type || undefined,
                error_code: rejection.code,
              },
            ]
          : [],
      );
      const requestedSessionId = createClientUuid();
      void createUploadSession({
        files: uploadFiles,
        rejectedFiles,
        sessionId: requestedSessionId,
      })
        .then((session) => {
          applyUploadSession(session);
          void loadLocalPending();
        })
        .catch(async (error) => {
          try {
            const recovered = await fetchUploadSession(requestedSessionId);
            applyUploadSession(recovered);
            return;
          } catch {
            // Keep the original safe upload error below.
          }
          updateLocalUploadQueue((current) =>
            current.map((item) =>
              items.some((created) => created.id === item.id)
                ? {
                    ...item,
                    status: "failed",
                    error:
                      error instanceof ApiError
                        ? error.message
                        : "上传会话暂时无法创建，请稍后重试",
                    retryable: false,
                  }
                : item,
            ),
          );
          setIntakeFeedback({
            kind: "network_error",
            total: prepared.length,
            accepted: 0,
            rejected: prepared.length,
            waitingBatches: 0,
            batchSizes: sizes,
            message: "上传会话未能创建；请检查网络后重新选择文件。",
          });
        });
    },
    [applyUploadSession, loadLocalPending, processLocalUploadQueue, updateLocalUploadQueue],
  );

  const retryLocalUpload = useCallback(
    (id: string) => {
      if (uploadSession?.items.some((item) => item.id === id)) {
        void retryUploadSessionItem(uploadSession.id, id)
          .then(applyUploadSession)
          .catch((error) => {
            updateLocalUploadQueue((items) =>
              items.map((item) =>
                item.id === id
                  ? {
                      ...item,
                      error: error instanceof ApiError ? error.message : "重试失败，请稍后再试",
                    }
                  : item,
              ),
            );
          });
        return;
      }
      updateLocalUploadQueue((items) =>
        items.map((item) =>
          item.id === id
            ? {
                ...item,
                status: "queued",
                error: null,
                ingestTaskId: null,
                pollAttempts: 0,
              }
            : item,
        ),
      );
      void processLocalUploadQueue();
    },
    [applyUploadSession, processLocalUploadQueue, updateLocalUploadQueue, uploadSession],
  );

  const removeLocalUpload = useCallback(
    (id: string) => {
      if (!uploadSession) {
        updateLocalUploadQueue((items) => items.filter((item) => item.id !== id));
        return;
      }
      void removeUploadSessionItem(uploadSession.id, id)
        .then((session) => {
          applyUploadSession(session);
          void loadLocalPending();
        })
        .catch((error) => {
          updateLocalUploadQueue((items) =>
            items.map((item) =>
              item.id === id
                ? {
                    ...item,
                    error: error instanceof ApiError ? error.message : "移除失败，请稍后再试",
                  }
                : item,
            ),
          );
        });
    },
    [applyUploadSession, loadLocalPending, updateLocalUploadQueue, uploadSession],
  );

  const removeFailedLocalUploads = useCallback(() => {
    if (!uploadSession) {
      updateLocalUploadQueue((items) => items.filter((item) => item.status !== "failed"));
      return;
    }
    void removeFailedUploadSessionItems(uploadSession.id)
      .then((session) => {
        applyUploadSession(session);
        void loadLocalPending();
      })
      .catch((error) => {
        setIntakeFeedback((current) => ({
          kind: "network_error",
          total: current?.total ?? uploadSession.total_files,
          accepted: current?.accepted ?? 0,
          rejected: current?.rejected ?? uploadSession.failed_files,
          waitingBatches: current?.waitingBatches ?? 0,
          batchSizes: current?.batchSizes ?? batchSizes(uploadSession.total_files),
          message: error instanceof ApiError ? error.message : "失败项清理未完成，请稍后重试。",
        }));
      });
  }, [applyUploadSession, loadLocalPending, updateLocalUploadQueue, uploadSession]);

  // 把一次 ai-result 的建议填入人工校正区（Path A / Path B 共用）。
  const applyAiResult = useCallback((ai: IngestAiResultDTO, fallbackTitle: string) => {
    setLlmStatus({
      status: ai.content_processing_status,
      provider: ai.llm_provider,
      summaryStatus: ai.summary_status,
      generationModelRef: ai.generation_model_ref,
    });
    setDesensitization({
      status: ai.desensitization_status,
      counts: ai.desensitization_counts,
      message: ai.desensitization_message,
    });
    setEditTitle(ai.suggested_title ?? fallbackTitle);
    setEditOneLiner(ai.suggested_one_liner ?? "");
    setEditSummary(ai.suggested_summary ?? "");
    setEditKeyPoints((ai.suggested_key_points ?? []).join("\n"));
    setEditTags((ai.suggested_tags ?? []).join(" · "));
    setEditAssetType(ai.suggested_asset_type ?? "methodology");
    setEditConfidentiality(ai.suggested_confidentiality_level ?? "L2");
    setEditAiAccess(ai.suggested_ai_access_level ?? "A2");
    setConfirmConfidence(ai.confidence != null ? `${Math.round(ai.confidence * 100)}%` : "—");
    setNaming(ai.naming_parsed_fields ?? null);
    setExtraction({
      status: ai.extraction_status,
      charCount: ai.extracted_char_count,
      isDuplicate: ai.is_possible_duplicate,
    });
  }, []);

  // 轮询 ai-result 至非 processing 或超时。
  const pollAiResult = useCallback(async (id: string, isCurrent: () => boolean) => {
    if (!isCurrent()) return null;
    let ai = await fetchIngestAiResult(id);
    if (!isCurrent()) return null;
    let attempts = 0;
    while (ai.status === "processing" && attempts < POLL_MAX_ATTEMPTS) {
      await sleep(POLL_INTERVAL_MS);
      if (!isCurrent()) return null;
      ai = await fetchIngestAiResult(id);
      if (!isCurrent()) return null;
      attempts += 1;
    }
    return ai;
  }, []);

  // Path A：点击真实待确认任务 → 拉取 AI 建议（与 Path B 同一 ai-result 接口）→ 填入
  // 人工校正区。处理中则轮询；失败/超时给安全提示且不可确认。
  const handleSelectPendingTask = useCallback(
    async (t: PendingIngestItemDTO) => {
      const runId = beginWorkflowRun();
      const isCurrent = () => isCurrentWorkflowRun(runId);
      setSelectedTaskName(t.source_file_name);
      setTaskId(t.id);
      setApiError(null);
      setProcessingNote(null);
      setResultAssetId(null);
      if (
        t.target_scope === "personal" ||
        t.target_scope === "project" ||
        t.target_scope === "company"
      ) {
        setTargetLibrary(t.target_scope);
      }
      if (t.target_project_id) setTargetProjectId(t.target_project_id);
      setFlowState("processing");
      try {
        const ai = await pollAiResult(t.id, isCurrent);
        if (!ai || !isCurrent()) return;
        applyAiResult(ai, t.source_file_name);
        if (ai.status === "processing") {
          setProcessingNote(
            "后台仍在处理该企微微盘文件（抽取 / LLM 内容处理），请稍后刷新重试，暂不可确认。",
          );
          setFlowState("processing");
          return;
        }
        if (ai.status === "failed") {
          setProcessingNote(
            `文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。请检查文件后重试，当前不可确认入库。`,
          );
          setFlowState("failed");
          return;
        }
        setFlowState("ready");
      } catch (e) {
        if (!isCurrent()) return;
        setApiError(e instanceof ApiError ? e.message : "加载该任务的 AI 建议失败");
        setFlowState("idle");
      }
    },
    [applyAiResult, beginWorkflowRun, isCurrentWorkflowRun, pollAiResult],
  );

  const handleFileSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setFolderDropNotice(null);
      if (e.target.files?.length) {
        void enqueueLocalFiles(e.target.files);
      } else {
        setIntakeFeedback({
          kind: "cancelled",
          total: 0,
          accepted: 0,
          rejected: 0,
          waitingBatches: 0,
          batchSizes: [],
          message: "未选择文件，本次操作已取消。",
        });
      }
      // Selecting the same file again must still enqueue a new, independent task.
      e.target.value = "";
    },
    [enqueueLocalFiles],
  );

  const handleFileDrop = useCallback(
    (files: Iterable<File>) => {
      setFolderDropNotice(null);
      void enqueueLocalFiles(files);
      if (fileRef.current) fileRef.current.value = "";
    },
    [enqueueLocalFiles],
  );

  const handleDataTransferDrop = useCallback(
    async (dataTransfer: DataTransfer) => {
      const runId = ++directoryReadRunRef.current;
      setFolderDropNotice(null);
      const result = await readDroppedFiles(
        dataTransfer,
        () => directoryReadRunRef.current === runId && activePath === "b",
      );
      if (directoryReadRunRef.current !== runId || activePath !== "b") return;
      setFolderDropNotice(result.notice);
      void enqueueLocalFiles(result.candidates);
      if (fileRef.current) fileRef.current.value = "";
    },
    [activePath, enqueueLocalFiles],
  );

  // Path B：上传真实文件字节 + 创建入库任务 + 异步轮询内容建议。
  const handleStart = useCallback(async () => {
    const runId = beginWorkflowRun();
    const isCurrent = () => isCurrentWorkflowRun(runId);
    if (!selectedFile) {
      setApiError("请先选择本地文件");
      return;
    }
    setFlowState("processing");
    setApiError(null);
    setProcessingNote(null);
    try {
      const up = await createIngestUpload({ file: selectedFile });
      if (!isCurrent()) return;
      setTaskId(up.ingest_task_id);
      const ai = await pollAiResult(up.ingest_task_id, isCurrent);
      if (!ai || !isCurrent()) return;
      if (ai.status === "processing") {
        setProcessingNote(
          "后台仍在处理该上传（抽取 / LLM 内容处理），请稍后刷新重试，暂不可提交。",
        );
        setFlowState("processing");
        return;
      }
      applyAiResult(ai, fileName);
      if (ai.status === "failed") {
        setProcessingNote(
          `文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。请检查文件后重新上传，当前不可提交入库。`,
        );
        setFlowState("failed");
        return;
      }
      setFlowState("ready");
    } catch (e) {
      if (!isCurrent()) return;
      setApiError(e instanceof ApiError ? e.message : "创建入库任务失败，请稍后重试");
      setFlowState("file_selected");
    }
  }, [selectedFile, fileName, applyAiResult, beginWorkflowRun, isCurrentWorkflowRun, pollAiResult]);

  // 轮询达到有限上限后，由用户显式重新检查同一真实任务，不创建伪进度或新任务。
  const handleRefreshProcessing = useCallback(async () => {
    const runId = beginWorkflowRun();
    const isCurrent = () => isCurrentWorkflowRun(runId);
    if (!taskId) return;
    setApiError(null);
    setProcessingNote(null);
    setFlowState("processing");
    try {
      const ai = await pollAiResult(taskId, isCurrent);
      if (!ai || !isCurrent()) return;
      applyAiResult(ai, activePath === "a" ? selectedTaskName : fileName);
      if (ai.status === "processing") {
        setProcessingNote("后台仍在处理，请稍后重新检查，当前不可确认入库。");
        return;
      }
      if (ai.status === "failed") {
        setProcessingNote(
          `文件处理失败：${ai.error_message ?? "无法从该文件抽取内容"}。当前不可确认入库。`,
        );
        setFlowState("failed");
        return;
      }
      setFlowState("ready");
    } catch (e) {
      if (!isCurrent()) return;
      setApiError(e instanceof ApiError ? e.message : "任务状态暂时无法获取，请稍后重试");
      setFlowState(activePath === "a" ? "idle" : "file_selected");
    }
  }, [
    activePath,
    applyAiResult,
    beginWorkflowRun,
    fileName,
    isCurrentWorkflowRun,
    pollAiResult,
    selectedTaskName,
    taskId,
  ]);

  // 两种来源共用同一确认链路。确认成功后展示资产链接；
  // Path A 额外刷新待确认列表。
  const handleSubmit = useCallback(async () => {
    const runId = beginWorkflowRun();
    const isCurrent = () => isCurrentWorkflowRun(runId);
    if (!taskId) return;
    setApiError(null);
    if (targetLibrary === "project" && !targetProjectId) {
      setApiError("请选择目标项目");
      return;
    }
    try {
      const tags = editTags
        .split(/[·,，、\s]+/)
        .map((t) => t.trim())
        .filter(Boolean);
      const keyPoints = editKeyPoints
        .split("\n")
        .map((t) => t.trim())
        .filter(Boolean);
      const res = await confirmIngest(taskId, {
        title: editTitle,
        one_liner: editOneLiner || undefined,
        summary: editSummary,
        key_points: keyPoints,
        tags,
        target_scope: targetLibrary,
        target_project_id: targetLibrary === "project" ? targetProjectId : undefined,
        target_zone: "material",
        asset_type: editAssetType,
        visibility: visibilityToKey[editVisibility] ?? "project_only",
        confidentiality_level: editConfidentiality,
        ai_access_level: editAiAccess,
        lifecycle_phase_key: editBizStage,
        // 仅传安全 model_ref；缺省（"" / WeKnora 未配置）则省略 → 后端走平台默认。
        embedding_model_ref: models.embeddingRef || undefined,
        rerank_model_ref: models.rerankRef || undefined,
      });
      if (!isCurrent()) return;
      setResultAssetId(res.result_asset_id);
      setSubmitReviewId(res.review_id ?? null);
      setSubmitIndexStatus(res.index_status ?? null);
      setFlowState("submitted");
      if (activePath === "a") void loadPending();
      if (activePath === "b") {
        removeLocalTaskEverywhere(taskId);
        void loadLocalPending();
      }
    } catch (e) {
      if (!isCurrent()) return;
      setApiError(e instanceof ApiError ? e.message : "提交入库失败");
    }
  }, [
    activePath,
    taskId,
    targetLibrary,
    targetProjectId,
    editTags,
    editTitle,
    editOneLiner,
    editSummary,
    editKeyPoints,
    editBizStage,
    editAssetType,
    editVisibility,
    editConfidentiality,
    editAiAccess,
    beginWorkflowRun,
    isCurrentWorkflowRun,
    loadPending,
    loadLocalPending,
    removeLocalTaskEverywhere,
    models.embeddingRef,
    models.rerankRef,
  ]);

  const toggleBatchTask = useCallback((id: string) => {
    setBatchSelection((selected) =>
      selected.includes(id) ? selected.filter((item) => item !== id) : [...selected, id],
    );
  }, []);

  const setBatchTasksSelected = useCallback((ids: string[], selected: boolean) => {
    setBatchSelection((current) => {
      const target = new Set(ids);
      if (!selected) return current.filter((id) => !target.has(id));
      return [...current, ...ids.filter((id) => !current.includes(id))];
    });
  }, []);

  // The queue is intentionally awaited one item at a time. Each request uses
  // that task's own AI result and destination metadata, so fields never leak
  // from one selected file into another.
  const handleBatchConfirm = useCallback(
    async (tasks: PendingIngestItemDTO[]) => {
      if (batchRunRef.current !== null || tasks.length === 0) return;
      const runId = beginWorkflowRun();
      const isCurrent = () => batchRunRef.current === runId && isCurrentWorkflowRun(runId);
      const updateBatchStatus = (
        update: (
          previous: Record<string, "waiting" | "processing" | "success" | "failed">,
        ) => Record<string, "waiting" | "processing" | "success" | "failed">,
      ) => {
        if (!isCurrent()) return;
        setBatchStatus(update);
      };
      batchRunRef.current = runId;
      setBatchBusy(true);
      setBatchOperation("confirm");
      setBatchErrors((previous) => {
        const next = { ...previous };
        tasks.forEach((task) => delete next[task.id]);
        return next;
      });
      let completed = false;
      updateBatchStatus((previous) => {
        const next = { ...previous };
        tasks.forEach((task) => {
          next[task.id] = "waiting";
        });
        return next;
      });
      try {
        for (const task of tasks) {
          if (!isCurrent()) return;
          updateBatchStatus((previous) => ({ ...previous, [task.id]: "processing" }));
          try {
            const ai = await pollAiResult(task.id, isCurrent);
            if (!isCurrent()) return;
            if (!ai || ai.status === "processing" || ai.status === "failed") {
              throw new Error("该资料尚未准备好确认入库");
            }
            const targetScope =
              task.target_scope === "project" || task.target_scope === "company"
                ? task.target_scope
                : "personal";
            if (targetScope === "project" && !task.target_project_id) {
              throw new Error("该项目资料缺少目标项目");
            }
            const title = ai.suggested_title?.trim() || task.suggested_title?.trim() || "";
            const summary = ai.suggested_summary?.trim() || ai.suggested_one_liner?.trim() || "";
            if (!title || !summary) throw new Error("该资料缺少可确认的标题或摘要");
            if (!isCurrent()) return;
            await confirmIngest(task.id, {
              title,
              one_liner: ai.suggested_one_liner || undefined,
              summary,
              key_points: ai.suggested_key_points?.filter(Boolean) || [],
              tags: ai.suggested_tags?.filter(Boolean) || [],
              target_scope: targetScope,
              target_project_id:
                targetScope === "project" ? task.target_project_id || undefined : undefined,
              target_zone: "material",
              asset_type: ai.suggested_asset_type || "methodology",
              visibility: "project_only",
              confidentiality_level: ai.suggested_confidentiality_level || "L2",
              ai_access_level: ai.suggested_ai_access_level || "A2",
              lifecycle_phase_key: ai.suggested_phase_key || undefined,
              embedding_model_ref: models.embeddingRef || undefined,
              rerank_model_ref: models.rerankRef || undefined,
            });
            if (!isCurrent()) return;
            if (activePath === "b") removeLocalTaskEverywhere(task.id);
            updateBatchStatus((previous) => ({ ...previous, [task.id]: "success" }));
          } catch {
            if (!isCurrent()) return;
            // One failure is shown on that row and never prevents the next task.
            updateBatchStatus((previous) => ({ ...previous, [task.id]: "failed" }));
          }
        }
        if (!isCurrent()) return;
        completed = true;
        setBatchSelection([]);
        if (activePath === "a") void loadPending();
        else void loadLocalPending();
      } finally {
        // A single-task selection can invalidate this run without going through
        // handleReset. Release only this batch's lock, never a newer batch's.
        if (batchRunRef.current === runId) {
          batchRunRef.current = null;
          setBatchBusy(false);
          setBatchOperation(null);
          if (!completed) {
            setBatchSelection([]);
            setBatchStatus({});
          }
        }
      }
    },
    [
      activePath,
      beginWorkflowRun,
      isCurrentWorkflowRun,
      loadLocalPending,
      loadPending,
      models.embeddingRef,
      models.rerankRef,
      pollAiResult,
      removeLocalTaskEverywhere,
    ],
  );

  // Permanent rejection intentionally reuses the existing one-item DELETE endpoint.
  // Awaiting each request preserves per-item authorization/audit and prevents parallel deletion.
  const handleBatchReject = useCallback(
    async (tasks: PendingIngestItemDTO[]) => {
      if (batchRunRef.current !== null || tasks.length === 0) return;
      const sourceAtStart = activePath;
      const runId = beginWorkflowRun();
      const isCurrent = () =>
        batchRunRef.current === runId &&
        isCurrentWorkflowRun(runId) &&
        activePath === sourceAtStart;
      batchRunRef.current = runId;
      setBatchBusy(true);
      setBatchOperation("reject");
      setBatchErrors((previous) => {
        const next = { ...previous };
        tasks.forEach((task) => delete next[task.id]);
        return next;
      });
      setBatchStatus((previous) => {
        const next = { ...previous };
        tasks.forEach((task) => {
          next[task.id] = "waiting";
        });
        return next;
      });

      const failed = new Set<string>();
      let completed = false;
      try {
        for (const task of tasks) {
          if (!isCurrent()) return;
          setBatchStatus((previous) => ({ ...previous, [task.id]: "processing" }));
          try {
            await deletePendingTask(task.id);
            if (!isCurrent()) return;
            setBatchStatus((previous) => ({ ...previous, [task.id]: "success" }));
            const removeTask = (items: PendingIngestItemDTO[]) =>
              items.filter((item) => item.id !== task.id);
            if (sourceAtStart === "a") {
              setPendingTasks(removeTask);
            } else {
              removeLocalTaskEverywhere(task.id);
            }
            setBatchSelection((selected) => selected.filter((id) => id !== task.id));
          } catch {
            if (!isCurrent()) return;
            failed.add(task.id);
            setBatchStatus((previous) => ({ ...previous, [task.id]: "failed" }));
            setBatchErrors((previous) => ({
              ...previous,
              [task.id]: "拒绝失败，任务仍保留，请重试",
            }));
          }
        }
        if (!isCurrent()) return;
        completed = true;
        if (sourceAtStart === "a") {
          void loadPending();
        } else {
          void loadLocalPending();
        }
        setBatchSelection((selected) => selected.filter((id) => failed.has(id)));
      } finally {
        if (batchRunRef.current === runId) {
          batchRunRef.current = null;
          setBatchBusy(false);
          setBatchOperation(null);
          if (!completed) {
            setBatchSelection([]);
            setBatchStatus({});
            setBatchErrors({});
          }
        }
      }
    },
    [
      activePath,
      beginWorkflowRun,
      isCurrentWorkflowRun,
      loadLocalPending,
      loadPending,
      removeLocalTaskEverywhere,
    ],
  );

  const handleReset = useCallback(() => {
    beginWorkflowRun();
    directoryReadRunRef.current += 1;
    batchRunRef.current = null;
    setBatchBusy(false);
    setBatchOperation(null);
    setBatchStatus({});
    setBatchErrors({});
    pendingRequestRef.current += 1;
    localPendingRequestRef.current += 1;
    setPendingLoading(false);
    setLocalPendingLoading(false);
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setFlowState("idle");
    setApiError(null);
    setFolderDropNotice(null);
    setProcessingNote(null);
    setLlmStatus(null);
    setDesensitization(null);
    setSelectedFile(null);
    setExtraction(null);
    setNaming(null);
    setFileName("");
    setFileSize(0);
    setFileType("");
    if (fileRef.current) fileRef.current.value = "";
    setSelectedTaskName("");
    setEditTitle("");
    setEditOneLiner("");
    setEditSummary("");
    setEditKeyPoints("");
    setLlmStatus(null);
    setEditTags("");
    setEditVisibility("项目内");
    setEditBizStage("行动辅导");
    setTargetLibrary("personal");
    setConfirmConfidence("—");
    setEditAssetType("methodology");
    setEditConfidentiality("L2");
    setEditAiAccess("A2");
    setTaskId(null);
    setResultAssetId(null);
    setSubmitReviewId(null);
    setSubmitIndexStatus(null);
    setApiError(null);
    setBatchSelection([]);
  }, [beginWorkflowRun]);

  // 删除待确认入库任务并清理 UI 状态，完成后刷新列表。
  const handleDeletePending = useCallback(
    async (tid: string) => {
      // Rejecting an ingest item is irreversible. Await it before resetting so
      // a failed delete leaves the current editor and source context available.
      setApiError(null);
      try {
        await deletePendingTask(tid);
        if (activePath === "b") removeLocalTaskEverywhere(tid);
        handleReset();
        // Refresh only the active source. The two lists have independent request
        // tokens, so a local action cannot leave the WeCom list loading (or vice versa).
        if (activePath === "a") void loadPending();
        else void loadLocalPending();
      } catch {
        setApiError("拒绝入库失败，任务仍保留，请重试");
      }
    },
    [activePath, handleReset, loadPending, loadLocalPending, removeLocalTaskEverywhere],
  );

  // 切换来源时清空当前流程 / 选中态，避免一处来源的校正数据残留到另一处。
  const switchPath = useCallback(
    (p: PathBranch) => {
      if (p === activePath) return;
      handleReset();
      // Keep the destination in an honest loading state between the source
      // switch render and the destination effect starting its request.
      if (p === "a") setPendingLoading(true);
      else setLocalPendingLoading(true);
      setActivePath(p);
    },
    [activePath, handleReset],
  );

  const confirmReady = flowState === "ready";
  const requiredFieldsOk =
    editTitle.trim().length > 0 &&
    (editSummary.trim().length > 0 || editOneLiner.trim().length > 0) &&
    (targetLibrary !== "project" || targetProjectId.length > 0);
  // 平台默认嵌入或问答模型未配置时禁用提交（models.blockSubmit），不静默走 .env 兜底。
  const canSubmit = confirmReady && requiredFieldsOk && !models.blockSubmit;
  const confirmSubmitted = flowState === "submitted";
  const awaitingProjectReview = confirmSubmitted && submitReviewId !== null;
  const sourceLabel = activePath === "a" ? "企微微盘" : "本地上传";
  const sourceFile = activePath === "a" ? selectedTaskName : fileName;
  const hasFile = flowState !== "idle";

  return {
    activePath,
    switchPath,
    flowState,
    fileName,
    fileSize,
    fileType,
    hasFile,
    extraction,
    desensitization,
    naming,
    fileRef,
    handleFileSelect,
    handleFileDrop,
    handleDataTransferDrop,
    folderDropNotice,
    intakeFeedback,
    localUploadQueue,
    uploadSession,
    retryLocalUpload,
    removeLocalUpload,
    removeFailedLocalUploads,
    handleStart,
    handleRefreshProcessing,
    handleReset,
    handleDeletePending,
    pendingTasks,
    pendingLoading,
    pendingError,
    loadPending,
    localPendingTasks,
    localPendingLoading,
    localPendingError,
    loadLocalPending,
    handleSelectPendingTask,
    batchSelection,
    batchStatus,
    batchBusy,
    batchOperation,
    batchErrors,
    toggleBatchTask,
    setBatchTasksSelected,
    handleBatchConfirm,
    handleBatchReject,
    taskId,
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
    editVisibility,
    setEditVisibility,
    editBizStage,
    setEditBizStage,
    editAssetType,
    setEditAssetType,
    editConfidentiality,
    setEditConfidentiality,
    editAiAccess,
    setEditAiAccess,
    targetLibrary,
    setTargetLibrary,
    targetProjectId,
    setTargetProjectId,
    projects,
    confirmConfidence,
    llmStatus,
    apiError,
    processingNote,
    confirmReady,
    confirmSubmitted,
    canSubmit,
    sourceLabel,
    sourceFile,
    resultAssetId,
    submitReviewId,
    awaitingProjectReview,
    submitIndexStatus,
    handleSubmit,
    models,
  };
}

export type UploadFlow = ReturnType<typeof useUploadFlow>;
