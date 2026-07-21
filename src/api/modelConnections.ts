// KAP-managed external OpenAI-compatible LLM connections. These endpoints never manage
// WeKnora models; credentials are write-only and responses contain safe model_ref values.
import { apiGet, apiPost, apiPut, apiDelete } from "./http";
import type {
  ModelConnectionDTO,
  ModelConnectionListDTO,
  ModelConnectionMutateDTO,
  ModelConnectionTestResponseDTO,
  ModelUsageAssignmentsDTO,
  ModelUsageAssignmentsUpdateDTO,
} from "../types/modelConnections";

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

// 删除模型连接。后端对默认用途连接返回 409，需先更换默认模型再删除。
export async function deleteModelConnection(modelRef: string): Promise<void> {
  await apiDelete<void>(`${CONNECTIONS}/items/${encodeURIComponent(modelRef)}`);
}
