// 统一检索 / 问答 API（POST /api/v1/knowledge/search，R3）的 DTO 类型。
//
// 安全字段边界：后端响应**绝不包含** WeKnora kb/doc/chunk id、storage_ref、
// source_file_ref、api_key、provider 内部标识、未脱敏原文 chunk。前端类型同样**不定义**
// 这些字段——original.chunks 的 content 已由后端实体脱敏，seq 为安全序号（非内部 id）。

export interface SearchFiltersDTO {
  zone?: string | null;
  tags?: string[];
  phase?: string | null;
  include_archived?: boolean;
}

export interface SearchRequestDTO {
  query: string;
  scope?: string | null;
  intent?: string | null;
  filters?: SearchFiltersDTO;
  want_original?: boolean;
  asset_id?: string | null;
}

// 阶段1摘要卡片：仅业务标识 + 安全摘要 + 相关度，无原文 / 内部 id。
export interface SearchCardDTO {
  asset_id: string;
  title: string;
  asset_type: string;
  scope: string;
  zone: string;
  confidentiality_level: string;
  phase: string | null;
  tags: string[];
  one_liner: string | null;
  detailed: string | null;
  key_points: string[];
  owner_name: string | null;
  maintainer_name: string | null;
  project_name: string | null;
  updated_at: string | null;
  version: string | null;
  relevance_score: number;
  can_view_original: boolean;
}

// 问答引用：业务标识 + 脱敏片段 + 使用的访问层，无内部 id。
export interface SearchCitationDTO {
  asset_id: string;
  asset_title: string;
  scope: string;
  cited_zone: string;
  used_access_layer: string;
  seq: number | null;
  snippet: string | null;
  citation_order: number;
}

export interface OriginalChunkDTO {
  seq: number | null;
  content: string; // 已实体脱敏
}

export interface OriginalDTO {
  asset_id: string | null;
  available: boolean;
  chunks: OriginalChunkDTO[];
  degraded_reason: string | null;
  owner_name: string | null;
  maintainer_name: string | null;
}

export interface SearchResponseDTO {
  intent: string;
  cards: SearchCardDTO[];
  answer: string | null;
  citations: SearchCitationDTO[];
  original: OriginalDTO | null;
  trace_id: string | null;
}
