// 入库流水线：Path B 真实文件上传、AI 处理结果轮询、历史导入待确认任务、
// 统一确认入库，以及 admin 入库运营列表。响应只含安全元数据（不含任何存储引用 / 路径 / URL）。
import { apiDelete, apiGet, apiPost, apiPostNoBody, apiUpload } from "./http";
import type {
  AdminIngestListResponseDTO,
  IngestAiResultDTO,
  IngestConfirmRequestDTO,
  IngestConfirmResponseDTO,
  IngestUploadResponseDTO,
  IngestTaskStatusDTO,
  MyUploadItemDTO,
  MyUploadListDTO,
  PendingIngestItemDTO,
  PendingIngestListResponseDTO,
  UploadSessionDTO,
  UploadSessionListDTO,
} from "../types/ingest";
import type { BulkOperationResponseDTO, IngestBulkOperationResponseDTO } from "../types/bulk";
import { runControlledBulkRequests } from "./bulk";

// 真实文件上传：以 multipart/form-data 发送选中的文件字节。后端写入受控存储并
// 只返回安全元数据（不返回任何存储引用 / 路径 / URL）。
export async function createIngestUpload(input: {
  file: File;
  targetScope?: string;
}): Promise<IngestUploadResponseDTO> {
  const form = new FormData();
  form.append("file", input.file, input.file.name);
  const formedOn = localDateFromMs(input.file.lastModified);
  if (formedOn) form.append("formed_on", formedOn);
  if (input.targetScope) form.append("target_scope", input.targetScope);
  return apiUpload<IngestUploadResponseDTO>(`/api/v1/ingest/upload`, form);
}

export async function createUploadSession(input: {
  files: File[];
  rejectedFiles?: Array<{
    file_name: string;
    file_size: number;
    file_type?: string;
    error_code:
      | "file_unreadable"
      | "file_read_timeout"
      | "macos_metadata"
      | "unsupported_file_type"
      | "file_too_large";
  }>;
  sessionId?: string;
  targetScope?: string;
  targetProjectId?: string;
}): Promise<UploadSessionDTO> {
  const form = new FormData();
  input.files.forEach((file) => form.append("files", file, file.name));
  // Preserve multipart order, including null entries and duplicate filenames.
  form.append(
    "client_formed_on",
    JSON.stringify(input.files.map((file) => localDateFromMs(file.lastModified))),
  );
  if (input.rejectedFiles?.length) {
    form.append("client_rejections", JSON.stringify(input.rejectedFiles));
  }
  if (input.sessionId) form.append("session_id", input.sessionId);
  if (input.targetScope) form.append("target_scope", input.targetScope);
  if (input.targetProjectId) form.append("target_project_id", input.targetProjectId);
  return apiUpload<UploadSessionDTO>(`/api/v1/ingest/upload-sessions`, form);
}

export interface UploadManifestInput {
  client_file_key: string;
  file_name: string;
  file_size: number;
  file_type?: string;
  formed_on?: string;
  transport_batch_index?: number;
  rejection?: {
    file_name: string;
    file_size: number;
    file_type?: string;
    error_code:
      | "file_unreadable"
      | "file_read_timeout"
      | "macos_metadata"
      | "unsupported_file_type"
      | "file_too_large";
  };
}

export async function initializeUploadSession(input: {
  sessionId: string;
  manifest: UploadManifestInput[];
  totalTransportBatches: number;
  targetScope?: string;
  targetProjectId?: string;
}): Promise<UploadSessionDTO> {
  return apiPost<UploadSessionDTO>("/api/v1/ingest/upload-sessions/init", {
    session_id: input.sessionId,
    manifest: input.manifest,
    total_transport_batches: input.totalTransportBatches,
    target_scope: input.targetScope ?? null,
    target_project_id: input.targetProjectId ?? null,
  });
}

export async function appendUploadSessionBatch(input: {
  sessionId: string;
  batchId: string;
  batchIndex: number;
  itemIds: string[];
  files: File[];
  signal?: AbortSignal;
}): Promise<UploadSessionDTO> {
  const form = new FormData();
  form.append("batch_id", input.batchId);
  form.append("batch_index", String(input.batchIndex));
  form.append("item_ids", JSON.stringify(input.itemIds));
  input.files.forEach((file) => form.append("files", file, file.name));
  return apiUpload<UploadSessionDTO>(
    `/api/v1/ingest/upload-sessions/${input.sessionId}/batches`,
    form,
    input.signal,
  );
}

export async function completeUploadSession(sessionId: string): Promise<UploadSessionDTO> {
  return apiPostNoBody<UploadSessionDTO>(`/api/v1/ingest/upload-sessions/${sessionId}/complete`);
}

export async function cancelUploadSession(sessionId: string): Promise<UploadSessionDTO> {
  return apiPostNoBody<UploadSessionDTO>(`/api/v1/ingest/upload-sessions/${sessionId}/cancel`);
}

export async function recordUploadTransportFailure(
  sessionId: string,
  itemIds: string[],
  errorCode: "proxy_rejected" | "upload_timeout" | "network_interrupted",
  batch?: { id: string; index: number },
): Promise<UploadSessionDTO> {
  return apiPost<UploadSessionDTO>(
    `/api/v1/ingest/upload-sessions/${sessionId}/transport-failure`,
    {
      item_ids: itemIds,
      error_code: errorCode,
      batch_id: batch?.id ?? null,
      batch_index: batch?.index ?? null,
    },
  );
}

export async function replaceUploadSessionItemBytes(input: {
  sessionId: string;
  itemId: string;
  file: File;
}): Promise<UploadSessionDTO> {
  const form = new FormData();
  form.append("file", input.file, input.file.name);
  const formedOn = localDateFromMs(input.file.lastModified);
  if (formedOn) form.append("formed_on", formedOn);
  return apiUpload<UploadSessionDTO>(
    `/api/v1/ingest/upload-sessions/${input.sessionId}/items/${input.itemId}/bytes`,
    form,
  );
}

export function localDateFromMs(ms: number): string | null {
  if (!Number.isFinite(ms) || ms <= 0) return null;
  const d = new Date(ms);
  if (!Number.isFinite(d.getTime())) return null;
  const y = d.getFullYear();
  const m = `${d.getMonth() + 1}`.padStart(2, "0");
  const day = `${d.getDate()}`.padStart(2, "0");
  return `${y}-${m}-${day}`;
}

export async function fetchUploadSessions(limit = 10): Promise<UploadSessionDTO[]> {
  const data = await apiGet<UploadSessionListDTO>(`/api/v1/ingest/upload-sessions?limit=${limit}`);
  return data.items;
}

export async function fetchUploadSession(
  sessionId: string,
  signal?: AbortSignal,
): Promise<UploadSessionDTO> {
  return apiGet<UploadSessionDTO>(`/api/v1/ingest/upload-sessions/${sessionId}`, signal);
}

export async function retryUploadSessionItem(
  sessionId: string,
  itemId: string,
): Promise<UploadSessionDTO> {
  return apiPostNoBody<UploadSessionDTO>(
    `/api/v1/ingest/upload-sessions/${sessionId}/items/${itemId}/retry`,
  );
}

export async function removeUploadSessionItem(
  sessionId: string,
  itemId: string,
): Promise<UploadSessionDTO> {
  return apiDelete<UploadSessionDTO>(`/api/v1/ingest/upload-sessions/${sessionId}/items/${itemId}`);
}

export async function removeFailedUploadSessionItems(sessionId: string): Promise<UploadSessionDTO> {
  return apiDelete<UploadSessionDTO>(`/api/v1/ingest/upload-sessions/${sessionId}/failed-items`);
}

export async function fetchIngestAiResult(taskId: string): Promise<IngestAiResultDTO> {
  return apiGet<IngestAiResultDTO>(`/api/v1/ingest/${taskId}/ai-result`);
}

export async function fetchIngestTaskStatus(taskId: string): Promise<IngestTaskStatusDTO> {
  return apiGet<IngestTaskStatusDTO>(`/api/v1/ingest/${taskId}/status`);
}

export async function retryIngestTask(taskId: string): Promise<IngestTaskStatusDTO> {
  return apiPostNoBody<IngestTaskStatusDTO>(`/api/v1/ingest/${taskId}/retry`);
}

// 历史导入+ Path B（本地上传）待确认任务列表。后端按权限只返回调用人可确认的任务，
// 仅安全元数据；纯 admin 403。前端不复制权限逻辑，只展示接口结果。
// 不再硬编码 source 过滤——默认获取所有来源的待确认任务。
export async function fetchPendingIngestTasks(source?: string): Promise<PendingIngestItemDTO[]> {
  const qs = new URLSearchParams();
  if (source) qs.set("source", source);
  const query = qs.toString();
  const data = await apiGet<PendingIngestListResponseDTO>(
    query ? `/api/v1/ingest/pending?${query}` : "/api/v1/ingest/pending",
  );
  return data.items;
}

export async function deletePendingTask(taskId: string): Promise<void> {
  await apiDelete<{ ok: boolean }>(`/api/v1/ingest/${taskId}`);
}

export async function confirmIngest(
  taskId: string,
  payload: IngestConfirmRequestDTO,
): Promise<IngestConfirmResponseDTO> {
  return apiPost<IngestConfirmResponseDTO>(`/api/v1/ingest/${taskId}/confirm`, payload);
}

export async function decideUploadDuplicate(input: {
  taskId: string;
  action: "skip" | "independent" | "keep";
  reason?: string;
  targetScope: "personal" | "project" | "company";
  targetProjectId?: string;
}): Promise<{
  task_id: string;
  status: string;
  decision: "skip" | "independent" | "batch_keep";
  skipped_task_ids: string[];
  duplicate: import("../types/ingest").UploadDuplicateDTO | null;
}> {
  return apiPost(`/api/v1/ingest/${input.taskId}/duplicate-decision`, {
    action: input.action,
    reason: input.reason ?? null,
    target_scope: input.targetScope,
    target_project_id: input.targetProjectId ?? null,
  });
}

export async function fetchMyUploads(
  filters: {
    scope?: string;
    finalStatus?: string;
    duplicateResult?: string;
    since?: string;
    until?: string;
  } = {},
): Promise<MyUploadItemDTO[]> {
  const query = new URLSearchParams();
  if (filters.scope) query.set("scope", filters.scope);
  if (filters.finalStatus) query.set("final_status", filters.finalStatus);
  if (filters.duplicateResult) query.set("duplicate_result", filters.duplicateResult);
  if (filters.since) query.set("since", filters.since);
  if (filters.until) query.set("until", filters.until);
  const suffix = query.toString();
  const response = await apiGet<MyUploadListDTO>(
    suffix ? `/api/v1/ingest/my-uploads?${suffix}` : "/api/v1/ingest/my-uploads",
  );
  return response.items;
}

export async function bulkConfirmIngest(input: {
  items: Array<{ taskId: string; confirmation: IngestConfirmRequestDTO }>;
  targetScope: "personal" | "project" | "company";
  targetProjectId?: string;
  onBatchCompleted?: (response: BulkOperationResponseDTO) => void;
}): Promise<IngestBulkOperationResponseDTO> {
  return runControlledBulkRequests({
    items: input.items,
    getItemId: (item) => item.taskId,
    submitBatch: (batch, context) =>
      apiPost<IngestBulkOperationResponseDTO>("/api/v1/ingest/bulk-confirm", {
        items: batch.map((item) => ({
          task_id: item.taskId,
          confirmation: item.confirmation,
        })),
        target_scope: input.targetScope,
        target_project_id: input.targetProjectId ?? null,
        client_operation_id: context.clientOperationId,
        request_index: context.requestIndex,
        request_count: context.requestCount,
        total_submitted: context.totalSubmitted,
      }),
    onBatchCompleted: input.onBatchCompleted
      ? (response) => input.onBatchCompleted?.(response)
      : undefined,
  });
}

// Admin 入库运营列表（仅安全运营元数据；admin / 治理角色，普通业务用户 403）。
export async function fetchAdminIngest(): Promise<AdminIngestListResponseDTO> {
  return apiGet<AdminIngestListResponseDTO>(`/api/v1/admin/ingest`);
}

// Explicit operator tools; the server remains the permission authority.
export function refreshIngestParse(taskId: string) {
  return apiPost<{ task_id: string; result_asset_id: string | null; parse_status: string | null }>(
    `/api/v1/ingest/${encodeURIComponent(taskId)}/refresh-parse`,
    {},
  );
}
