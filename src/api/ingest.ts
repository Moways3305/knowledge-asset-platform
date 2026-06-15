// 入库流水线：Path B 真实文件上传、AI 处理结果轮询、Path A（企微微盘）待确认任务、
// 统一确认入库，以及 admin 入库运营列表。响应只含安全元数据（不含任何存储引用 / 路径 / URL）。
import {
  apiGet,
  apiPost,
  csrfHeaders,
  handleResponse,
  withCsrfRetry,
  BASE_URL,
} from "./http";
import type {
  AdminIngestListResponseDTO,
  IngestAiResultDTO,
  IngestConfirmRequestDTO,
  IngestConfirmResponseDTO,
  IngestUploadResponseDTO,
  PendingIngestItemDTO,
  PendingIngestListResponseDTO,
} from "../types/ingest";

// 真实文件上传：以 multipart/form-data 发送选中的文件字节。后端写入受控存储并
// 只返回安全元数据（不返回任何存储引用 / 路径 / URL）。
export async function createIngestUpload(input: {
  file: File;
  targetScope?: string;
}): Promise<IngestUploadResponseDTO> {
  const form = new FormData();
  form.append("file", input.file, input.file.name);
  if (input.targetScope) form.append("target_scope", input.targetScope);
  return withCsrfRetry(async () => {
    const resp = await fetch(`${BASE_URL}/api/v1/ingest/upload`, {
      method: "POST",
      headers: await csrfHeaders(), // 不设 Content-Type：浏览器自动带 multipart boundary
      body: form,
      credentials: "include",
    });
    return handleResponse<IngestUploadResponseDTO>(resp);
  });
}

export async function fetchIngestAiResult(taskId: string): Promise<IngestAiResultDTO> {
  return apiGet<IngestAiResultDTO>(`/api/v1/ingest/${taskId}/ai-result`);
}

// Path A（企微微盘）待确认任务列表。后端按权限只返回调用人可确认的任务，
// 仅安全元数据；纯 admin 403。前端不复制权限逻辑，只展示接口结果。
export async function fetchPendingIngestTasks(
  source = "path_a_wecom"
): Promise<PendingIngestItemDTO[]> {
  const qs = new URLSearchParams({ source });
  const data = await apiGet<PendingIngestListResponseDTO>(
    `/api/v1/ingest/pending?${qs.toString()}`
  );
  return data.items;
}

export async function confirmIngest(
  taskId: string,
  payload: IngestConfirmRequestDTO
): Promise<IngestConfirmResponseDTO> {
  return apiPost<IngestConfirmResponseDTO>(`/api/v1/ingest/${taskId}/confirm`, payload);
}

// Admin 入库运营列表（仅安全运营元数据；admin / 治理角色，普通业务用户 403）。
export async function fetchAdminIngest(): Promise<AdminIngestListResponseDTO> {
  return apiGet<AdminIngestListResponseDTO>(`/api/v1/admin/ingest`);
}
