// Safe model references are used for selection and assignment; raw provider credentials never
// enter frontend persistence or response state.
import { apiGet } from "./http";
import type { ModelOptionsResponseDTO } from "../types/weknoraAdmin";

// 顾问入库 / 建库前查看可选模型（可按 type 过滤，如 embedding / rerank）。
// 返回 default_missing：平台默认嵌入或问答模型未配置时为 true，前端据此禁用提交。
export async function fetchModelOptions(type?: string): Promise<ModelOptionsResponseDTO> {
  const qs = type ? `?type=${encodeURIComponent(type)}` : "";
  return apiGet<ModelOptionsResponseDTO>(`/api/v1/weknora/model-options${qs}`);
}
