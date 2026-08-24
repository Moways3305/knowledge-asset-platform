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
  transportBatchNumber?: number;
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

export const LOCAL_UPLOAD_MAX_BYTES = 25 * 1024 * 1024;
export const TRANSPORT_BATCH_MAX_BYTES = 20 * 1024 * 1024;
export const TRANSPORT_BATCH_MAX_FILES = 10;
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
  "png",
  "jpg",
  "jpeg",
  "tif",
  "tiff",
  "bmp",
  "webp",
]);

export function buildUploadTransportBatches<T extends { file: File }>(items: T[]): T[][] {
  const batches: T[][] = [];
  let current: T[] = [];
  let currentBytes = 0;
  for (const item of items) {
    const mustBeAlone = item.file.size > TRANSPORT_BATCH_MAX_BYTES;
    if (
      current.length > 0 &&
      (mustBeAlone ||
        current.length >= TRANSPORT_BATCH_MAX_FILES ||
        currentBytes + item.file.size > TRANSPORT_BATCH_MAX_BYTES)
    ) {
      batches.push(current);
      current = [];
      currentBytes = 0;
    }
    current.push(item);
    currentBytes += item.file.size;
    if (mustBeAlone || current.length >= TRANSPORT_BATCH_MAX_FILES) {
      batches.push(current);
      current = [];
      currentBytes = 0;
    }
  }
  if (current.length > 0) batches.push(current);
  return batches;
}

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
