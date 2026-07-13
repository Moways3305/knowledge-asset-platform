// Safe model references are used for selection and assignment; raw provider credentials never
// enter frontend persistence or response state.
import { apiGet, apiPost, apiPut } from "./http";
import type {
  ModelConnectionDTO,
  ModelConnectionListDTO,
  ModelConnectionMutateDTO,
  ModelConnectionTestResponseDTO,
  ModelUsageAssignmentsDTO,
  ModelUsageAssignmentsUpdateDTO,
  ModelOptionsResponseDTO,
} from "../types/weknoraAdmin";

// 顾问入库 / 建库前查看可选模型（可按 type 过滤，如 embedding / rerank）。
// 返回 default_missing：平台默认嵌入或问答模型未配置时为 true，前端据此禁用提交。
export async function fetchModelOptions(type?: string): Promise<ModelOptionsResponseDTO> {
  const qs = type ? `?type=${encodeURIComponent(type)}` : "";
  return apiGet<ModelOptionsResponseDTO>(`/api/v1/weknora/model-options${qs}`);
}

const CONNECTIONS = "/api/v1/admin/model-connections";

export async function fetchModelConnections(): Promise<ModelConnectionListDTO> {
  return apiGet<ModelConnectionListDTO>(CONNECTIONS);
}

export async function createModelConnection(
  body: ModelConnectionMutateDTO,
): Promise<ModelConnectionDTO> {
  return apiPost<ModelConnectionDTO>(CONNECTIONS, body);
}

export async function updateModelConnection(
  modelRef: string,
  body: ModelConnectionMutateDTO,
): Promise<ModelConnectionDTO> {
  return apiPut<ModelConnectionDTO>(`${CONNECTIONS}/items/${encodeURIComponent(modelRef)}`, body);
}

export async function testModelConnection(
  modelRef: string,
): Promise<ModelConnectionTestResponseDTO> {
  return apiPost<ModelConnectionTestResponseDTO>(
    `${CONNECTIONS}/items/${encodeURIComponent(modelRef)}/test`,
    {},
  );
}

export async function fetchModelUsageAssignments(): Promise<ModelUsageAssignmentsDTO> {
  return apiGet<ModelUsageAssignmentsDTO>(`${CONNECTIONS}/usages/current`);
}

export async function updateModelUsageAssignments(
  body: ModelUsageAssignmentsUpdateDTO,
): Promise<ModelUsageAssignmentsDTO> {
  return apiPut<ModelUsageAssignmentsDTO>(`${CONNECTIONS}/usages/current`, body);
}
