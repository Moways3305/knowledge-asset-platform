// WeKnora 模型选择 API（PBC-38）。
// - 顾问只读模型选项：GET /api/v1/weknora/model-options（业务用户可读，仅安全字段）。
// - 平台默认模型读/写：/api/v1/admin/weknora/default-models（读 admin/治理，写仅 admin）。
// 安全边界：前端只用对底座 id 不可逆的 model_ref 选择模型；绝不接触/提交/展示真实 model_id /
// api_key / base_url。model_ref 仅用于请求与内存状态，绝不写入 localStorage / sessionStorage。
import { apiGet, apiPut } from "./http";
import type {
  DefaultModelsDTO,
  DefaultModelsUpdateRequestDTO,
  GenerationModelOptionsResponseDTO,
  GenerationModelSelectionRequestDTO,
  GenerationModelSelectionResponseDTO,
  ModelOptionsResponseDTO,
} from "../types/weknoraAdmin";

// 顾问入库 / 建库前查看可选模型（可按 type 过滤，如 embedding / rerank）。
// 返回 default_missing：平台默认嵌入或问答模型未配置时为 true，前端据此禁用提交。
export async function fetchModelOptions(type?: string): Promise<ModelOptionsResponseDTO> {
  const qs = type ? `?type=${encodeURIComponent(type)}` : "";
  return apiGet<ModelOptionsResponseDTO>(`/api/v1/weknora/model-options${qs}`);
}

// 读平台默认模型（admin / boss / 咨询总监）。只回安全 model_ref + 名称。
export async function fetchDefaultModels(): Promise<DefaultModelsDTO> {
  return apiGet<DefaultModelsDTO>(`/api/v1/admin/weknora/default-models`);
}

// 改平台默认模型（仅 admin）。前端只提交 model_ref，后端解析真实 id；响应/审计无真实 id。
export async function updateDefaultModels(
  body: DefaultModelsUpdateRequestDTO,
): Promise<DefaultModelsDTO> {
  return apiPut<DefaultModelsDTO>(`/api/v1/admin/weknora/default-models`, body);
}

// KAP 内容生成模型：标题 / 摘要 / 标签建议。与 WeKnora 知识库 embedding/rerank/问答模型分离。
export async function fetchGenerationModelOptions(): Promise<GenerationModelOptionsResponseDTO> {
  return apiGet<GenerationModelOptionsResponseDTO>(`/api/v1/generation/model-options`);
}

export async function updateGenerationDefaultModel(
  body: GenerationModelSelectionRequestDTO,
): Promise<GenerationModelSelectionResponseDTO> {
  return apiPut<GenerationModelSelectionResponseDTO>(
    `/api/v1/admin/generation/default-model`,
    body,
  );
}
