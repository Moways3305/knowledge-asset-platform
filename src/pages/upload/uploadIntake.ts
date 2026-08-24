import { UNREADABLE_FILE_MESSAGE } from "./folderDrop";
import type { IngestTaskStage } from "../../types/ingest";

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
  retryCount?: number;
  lastAttemptAt?: string;
  processingStage?: IngestTaskStage;
}

export type IntakeRejectionCode =
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

export function localFileError(file: File): { code: IntakeRejectionCode; message: string } | null {
  const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (!LOCAL_UPLOAD_EXTENSIONS.has(extension)) {
    return { code: "unsupported_file_type", message: "该文件类型暂不支持上传" };
  }
  if (file.size > LOCAL_UPLOAD_MAX_BYTES) {
    return { code: "file_too_large", message: "文件超过 25 MiB 大小上限" };
  }
  return null;
}

export function uploadBatchSizes(total: number): number[] {
  return Array.from({ length: Math.ceil(total / 200) }, (_, index) =>
    Math.min(200, total - index * 200),
  );
}

export async function probeReadableFile(
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
