import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { ApiError, createClientUuid } from "../../api/http";
import {
  createIngestUpload,
  createUploadSession,
  fetchIngestTaskStatus,
  fetchUploadSession,
  fetchUploadSessions,
  removeFailedUploadSessionItems,
  removeUploadSessionItem,
  retryUploadSessionItem,
} from "../../api/ingest";
import type { PendingIngestItemDTO, UploadSessionDTO } from "../../types/ingest";
import { POLL_INTERVAL_MS, POLL_MAX_ATTEMPTS, type PathBranch } from "./uploadConstants";
import {
  isMacosMetadataPath,
  MACOS_METADATA_MESSAGE,
  readDroppedFiles,
  safeRejectedDisplayName,
  UNREADABLE_FILE_MESSAGE,
  type DroppedFileCandidate,
} from "./folderDrop";
import {
  localFileError,
  probeReadableFile,
  uploadBatchSizes as batchSizes,
  type LocalUploadQueueItem,
  type UploadIntakeFeedback,
} from "./uploadIntake";

interface UploadIntakeOptions {
  activePath: PathBranch;
  loadLocalPending: () => Promise<void>;
  setLocalPendingTasks: Dispatch<SetStateAction<PendingIngestItemDTO[]>>;
}

export function useUploadIntake({
  activePath,
  loadLocalPending,
  setLocalPendingTasks,
}: UploadIntakeOptions) {
  const [localUploadQueue, setLocalUploadQueue] = useState<LocalUploadQueueItem[]>([]);
  const [uploadSession, setUploadSession] = useState<UploadSessionDTO | null>(null);
  const [folderDropNotice, setFolderDropNotice] = useState<string | null>(null);
  const [intakeFeedback, setIntakeFeedback] = useState<UploadIntakeFeedback | null>(null);
  const localUploadQueueRef = useRef<LocalUploadQueueItem[]>([]);
  const localUploadWorkerRef = useRef(false);
  const localStatusPollingRef = useRef(false);
  const localStatusPollRunRef = useRef(0);
  const localUploadSequenceRef = useRef(0);
  const directoryReadRunRef = useRef(0);
  const fileRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);

  useEffect(
    () => () => {
      localStatusPollRunRef.current += 1;
      directoryReadRunRef.current += 1;
    },
    [],
  );

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
      error: item.status === "failed" ? item.error_message : null,
      ingestTaskId: null,
      pollAttempts: 0,
      batchNumber: item.batch_number,
      sameNameWarning: item.same_name_warning,
      retryable: item.retryable,
      processingStage: item.processing_stage ?? undefined,
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
    [setLocalPendingTasks, updateLocalUploadQueue],
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
                      processingStage: status.stage,
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
                      processingStage: status.stage,
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
                candidate.id === item.id
                  ? { ...candidate, pollAttempts, processingStage: status.stage }
                  : candidate,
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

  const handleFolderSelect = useCallback(
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
          message: "未选择文件夹，本次操作已取消。",
        });
      }
      e.target.value = "";
    },
    [enqueueLocalFiles],
  );

  const handleFileDrop = useCallback(
    (files: Iterable<File>) => {
      setFolderDropNotice(null);
      void enqueueLocalFiles(files);
      if (fileRef.current) fileRef.current.value = "";
      if (folderRef.current) folderRef.current.value = "";
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
      if (folderRef.current) folderRef.current.value = "";
    },
    [activePath, enqueueLocalFiles],
  );
  const cancelIntakeRuns = useCallback(() => {
    localStatusPollRunRef.current += 1;
    directoryReadRunRef.current += 1;
    setFolderDropNotice(null);
    if (fileRef.current) fileRef.current.value = "";
    if (folderRef.current) folderRef.current.value = "";
  }, []);

  return {
    localUploadQueue,
    uploadSession,
    folderDropNotice,
    setFolderDropNotice,
    intakeFeedback,
    setIntakeFeedback,
    fileRef,
    folderRef,
    retryLocalUpload,
    removeLocalUpload,
    removeFailedLocalUploads,
    handleFileSelect,
    handleFolderSelect,
    handleFileDrop,
    handleDataTransferDrop,
    removeLocalTaskEverywhere,
    cancelIntakeRuns,
  };
}
