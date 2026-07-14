// 模型配置中心 DTO。安全边界：绝不承载 WeKnora api_key / base_url 真实值 /
// server-only model_id / weknora_kb_id / 内部存储引用 / 原始 payload。前端用对底座 id 不可逆的
// model_ref 选择模型；写操作的访问密钥 / API 地址只单向上送，保存后不回显。

export type ModelTypeAlias = "chat" | "embedding" | "rerank" | "vllm" | "asr";

export interface ModelDTO {
  model_ref: string;
  name: string;
  type: string;
  source: string | null;
  provider: string | null;
  enabled: boolean;
  is_builtin: boolean;
  description: string | null;
}

export interface ModelSlotDTO {
  model_ref: string | null;
  name: string | null;
  type: string | null;
  provider: string | null;
}

export interface KbConfigDTO {
  mapping_id: string;
  scope: string;
  kb_name: string;
  project_name: string | null;
  owner_name: string | null;
  mapping_status: string;
  chat: ModelSlotDTO | null;
  embedding: ModelSlotDTO | null;
  rerank: ModelSlotDTO | null;
  multimodal: ModelSlotDTO | null;
  config_error: string | null;
}

export interface KbInitUpdateRequestDTO {
  chat_model_ref?: string | null;
  embedding_model_ref?: string | null;
  rerank_model_ref?: string | null;
  multimodal_ref?: string | null;
}

// ---- 顾问只读模型选项（PBC-38）----
// 安全展示字段；绝不含 server-only 真实 model_id / api_key / base_url。
export interface ModelOptionDTO {
  model_ref: string;
  name: string;
  type: string;
  provider: string | null;
  description: string | null;
  enabled: boolean;
  is_default: boolean;
}

// default_missing：平台默认嵌入或问答模型未配置 → 前端据此禁用提交并提示联系管理员。
export interface ModelOptionsResponseDTO {
  items: ModelOptionDTO[];
  default_missing: boolean;
}

export interface ModelConnectionTestResponseDTO {
  success: boolean;
  message: string;
  duration_ms: number;
}

// ---- PBC-48 unified model connections and usage assignments ----
export type ModelCapabilityType = "chat" | "embedding" | "rerank";
export type ModelUsageKey =
  | "content_generation"
  | "knowledge_embedding"
  | "knowledge_chat"
  | "knowledge_rerank";

export interface ModelConnectionDTO {
  model_ref: string;
  display_name: string;
  capability_type: ModelCapabilityType;
  provider: string | null;
  model_name: string;
  enabled: boolean;
  health_status: "configured" | "registered" | "untested" | string;
  available_usages: ModelUsageKey[];
  legacy_adapter: boolean;
}

export interface ModelConnectionListDTO {
  items: ModelConnectionDTO[];
  total: number;
  warning: string | null;
}

export interface ModelConnectionMutateDTO {
  display_name: string;
  capability_type: ModelCapabilityType;
  provider: string;
  model_name: string;
  base_url?: string | null;
  api_key?: string | null;
  enabled: boolean;
}

export interface ModelUsageSlotDTO {
  model_ref: string | null;
  display_name: string | null;
  capability_type: ModelCapabilityType | null;
}

export interface ModelUsageAssignmentsDTO {
  content_generation: ModelUsageSlotDTO | null;
  knowledge_embedding: ModelUsageSlotDTO | null;
  knowledge_chat: ModelUsageSlotDTO | null;
  knowledge_rerank: ModelUsageSlotDTO | null;
}

export interface ModelUsageAssignmentsUpdateDTO {
  content_generation_ref?: string | null;
  knowledge_embedding_ref?: string | null;
  knowledge_chat_ref?: string | null;
  knowledge_rerank_ref?: string | null;
}
