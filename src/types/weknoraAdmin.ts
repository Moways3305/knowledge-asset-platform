// 模型配置中心 DTO。安全边界：绝不承载 WeKnora api_key / base_url 真实值 /
// server-only model_id / weknora_kb_id / 内部存储引用 / 原始 payload。前端用对底座 id 不可逆的
// model_ref 选择模型；写操作的访问密钥 / API 地址只单向上送，保存后不回显。

export type ModelTypeAlias = "chat" | "embedding" | "rerank" | "vllm" | "asr";

export interface ProviderDTO {
  value: string;
  label: string;
  description: string | null;
  model_types: string[];
}

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

export interface ModelMutateRequestDTO {
  name: string;
  type: string;
  source: string;
  provider?: string | null;
  base_url?: string | null;
  api_key?: string | null;
  description?: string | null;
  dimension?: number | null;
}

export interface ModelMutateResponseDTO {
  model_ref: string;
  name: string;
  type: string;
  provider: string | null;
  status: string;
}

export interface ModelCheckRequestDTO {
  model_type: string;
  api_url: string;
  api_key: string;
  model: string;
}

export interface ModelCheckResponseDTO {
  success: boolean;
  message: string;
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

