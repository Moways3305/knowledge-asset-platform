// Agent / Dify Gateway API 的 DTO 类型。
// 引用只含安全展示字段，不含对象存储 / 向量库 / Dify 内部标识。

export interface AgentCitationDTO {
  asset_id: string;
  asset_title: string;
  scope: string;
  cited_zone: string;
  used_access_layer: string;
  is_pending_review: boolean;
  is_asset_zone: boolean;
  citation_order: number;
  // 引用来源安全序号 + 脱敏片段（可空；不含任何 WeKnora 内部标识）。
  seq?: number | null;
  snippet?: string | null;
}

export interface ProjectQaResponseDTO {
  call_id: string;
  response_text: string;
  model_key: string;
  decision_status: string;
  citations: AgentCitationDTO[];
  trace_id: string | null;
  created_at: string;
}

export interface ProjectQaModelOptionDTO {
  model_ref: string;
  display_name: string;
  is_default: boolean;
}

export interface ProjectQaModelOptionsResponseDTO {
  items: ProjectQaModelOptionDTO[];
  total: number;
}
