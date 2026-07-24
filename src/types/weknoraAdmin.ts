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

export interface WeknoraDefaultModelsDTO {
  embedding: ModelSlotDTO | null;
  rerank: ModelSlotDTO | null;
  chat: ModelSlotDTO | null;
  multimodal: ModelSlotDTO | null;
  updated_at: string | null;
}

export interface WeknoraDefaultModelsUpdateDTO {
  embedding_model_ref?: string | null;
  rerank_model_ref?: string | null;
  chat_model_ref?: string | null;
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

// ---- WeKnora 模型 CRUD ----
export interface WeknoraModelMutateDTO {
  name: string;
  type: string;
  source?: string;
  provider?: string | null;
  base_url?: string | null;
  api_key?: string | null;
  description?: string | null;
  dimension?: number | null;
  enabled?: boolean | null;
}

export interface WeknoraModelMutateResponseDTO {
  model_ref: string;
  name: string;
  type: string;
  provider: string | null;
  status: string;
}

export interface WeknoraModelCheckDTO {
  model_type: string;
  api_url: string;
  api_key: string;
  model: string;
}

export interface WeknoraModelCheckResponseDTO {
  success: boolean;
  message: string;
}

export interface WeknoraModelDeleteResponseDTO {
  deleted: boolean;
}
