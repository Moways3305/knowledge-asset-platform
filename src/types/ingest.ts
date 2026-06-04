// 入库流水线 API 的 DTO 类型（IMPLEMENT-05，Path B）。

export interface IngestUploadResponseDTO {
  ingest_task_id: string;
  status: string;
  upload_url: null;
}

// 规范命名解析结果（后端确定性拼装；存于 naming_parsed_fields）。
// suggested_title 即由这些组件拼成的 normalized_title。
export interface NamingFields {
  primary_category: string;
  secondary_category: string;
  topic: string;
  subject_or_client: string;
  date: string;
  version: string;
  confidentiality_level: string;
  ai_access_level: string;
  normalized_title: string;
  // AI 推断字段（含安全默认）；missing 子集为"待人工校正"。
  inferred_fields: string[];
  missing_fields: string[];
  source_file_name: string;
  original_naming_compliant: boolean;
}

export interface IngestAiResultDTO {
  ingest_task_id: string;
  status: string;
  suggested_title: string | null;
  // R2 三层摘要建议 + 内容处理元数据。
  suggested_one_liner: string | null;
  suggested_summary: string | null;
  suggested_key_points: string[] | null;
  suggested_tags: string[] | null;
  llm_provider: string | null;
  llm_model: string | null;
  content_processing_status: string | null;
  suggested_asset_type: string | null;
  suggested_confidentiality_level: string | null;
  suggested_ai_access_level: string | null;
  suggested_phase_key: string | null;
  confidence: number | null;
  naming_compliant: boolean | null;
  naming_parsed_fields: NamingFields | null;
  naming_anomalies: unknown[] | null;
  // 抽取与去重（IMPLEMENT-14）。extracted_text_preview 仅完整视图返回。
  extraction_status: string | null;
  extracted_char_count: number | null;
  error_type: string | null;
  error_message: string | null;
  is_possible_duplicate: boolean;
  duplicate_of_task_id: string | null;
  duplicate_of_asset_id: string | null;
  extracted_text_preview: string | null;
}

export interface IngestConfirmRequestDTO {
  title: string;
  one_liner?: string;
  summary?: string;
  key_points?: string[];
  tags: string[];
  target_scope: "personal" | "project" | "company";
  target_project_id?: string;
  target_zone?: string;
  asset_type: string;
  visibility?: string;
  confidentiality_level: string;
  ai_access_level: string;
  lifecycle_phase_key?: string;
}

export interface IngestConfirmResponseDTO {
  task_id: string;
  status: string;
  result_asset_id: string;
}

// 运营视图（admin / 治理角色）：仅安全运营元数据，无业务原文 / 抽取全文 / 存储引用 / 外部系统内部 id。
export interface AdminIngestItemDTO {
  id: string;
  source: string;
  source_file_name: string;
  status: string;
  target_scope: string | null;
  confidentiality_level: string | null;
  ai_access_level: string | null;
  confidence: number | null;
  naming_compliant: boolean | null;
  extraction_status: string | null;
  error_type: string | null;
  error_message: string | null;
  result_asset_id: string | null;
  created_at: string | null;
}

export interface AdminIngestListResponseDTO {
  items: AdminIngestItemDTO[];
  total: number;
}

// 业务侧待确认任务（PBC-07，/upload Path A 面板）。仅安全元数据；
// 无 source_file_ref / storage_ref / WeCom file_id / 下载 URL / token / WeKnora id。
export interface PendingIngestItemDTO {
  id: string;
  source: string;
  status: string;
  source_file_name: string;
  target_scope: string | null;
  target_project_id: string | null;
  extraction_status: string | null;
  error_type: string | null;
  error_message: string | null;
  suggested_title: string | null;
  suggested_one_liner: string | null;
  naming_parsed_fields: NamingFields | null;
  confidence: number | null;
  result_asset_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PendingIngestListResponseDTO {
  items: PendingIngestItemDTO[];
  total: number;
}
