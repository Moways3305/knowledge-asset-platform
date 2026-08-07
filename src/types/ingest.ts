// 入库流水线 API 的 DTO 类型。

export interface IngestUploadResponseDTO {
  ingest_task_id: string;
  status: string;
  upload_url: null;
}

export type UploadSessionItemState =
  | "waiting"
  | "uploading"
  | "processing"
  | "awaiting_confirmation"
  | "completed"
  | "failed"
  | "cancelled";

export interface UploadSessionItemDTO {
  id: string;
  ordinal: number;
  batch_number: number;
  file_name: string;
  file_size: number;
  file_type: string | null;
  status: UploadSessionItemState;
  error_code: string | null;
  error_message: string | null;
  same_name_warning: boolean;
  retryable: boolean;
}

export interface UploadSessionDTO {
  id: string;
  status: string;
  total_files: number;
  completed_files: number;
  processing_files: number;
  waiting_files: number;
  failed_files: number;
  current_batch_number: number | null;
  total_batches: number;
  created_at: string;
  updated_at: string;
  items: UploadSessionItemDTO[];
}

export interface UploadSessionListDTO {
  items: UploadSessionDTO[];
  total: number;
}

export type IngestTaskStage =
  | "upload_saved"
  | "text_extraction"
  | "content_generation"
  | "awaiting_confirmation"
  | "confirmation"
  | "indexing_queued"
  | "indexing_in_progress"
  | "completed"
  | "failed"
  | "degraded_complete";

export type IngestTaskWorkflowStatus =
  | "processing"
  | "action_required"
  | "waiting"
  | "completed"
  | "degraded"
  | "failed";

export interface IngestTaskNextActionDTO {
  key: string;
  route_key: string | null;
  enabled: boolean;
}

export interface IngestTaskSafeErrorDTO {
  code: string;
  message: string;
  recovery_hint: string;
}

export interface IngestTaskStatusDTO {
  task_id: string;
  stage: IngestTaskStage;
  status: IngestTaskWorkflowStatus;
  updated_at: string | null;
  retryable: boolean;
  next_action: IngestTaskNextActionDTO | null;
  error: IngestTaskSafeErrorDTO | null;
  result_asset_id: string | null;
  review_id: string | null;
}

// 历史命名解析兼容元数据；suggested_title 的现行语义仅为干净主题。
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
  category_suggestion?: {
    suggested_category_id: string | null;
    category_source: import("./naming").CategorySuggestionSource;
    category_confidence: "high" | "medium" | "low";
    category_reason: string;
    candidate_rule_revision: number | null;
    target_scope?: "project" | "company";
    target_project_id?: string | null;
    status: "classified" | "needs_manual" | "failed" | "unchanged";
    retryable?: boolean;
  };
}

export interface IngestAiResultDTO {
  ingest_task_id: string;
  status: string;
  suggested_title: string | null;
  // 三层摘要建议 + 内容处理元数据。
  suggested_one_liner: string | null;
  suggested_summary: string | null;
  summary: string | null;
  summary_status: "processing" | "generated" | "pending_model_config" | "failed" | null;
  generation_model_ref: string | null;
  suggested_key_points: string[] | null;
  suggested_tags: string[] | null;
  llm_provider: string | null;
  llm_model: string | null;
  content_processing_status: string | null;
  // 入库前置规则脱敏安全元数据（仅状态 + 类别计数 + 人读文案；
  // 不含脱敏前/后正文、脱敏文本 ref、原始文件 ref）。
  // status: applied | unchanged | skipped | failed。
  desensitization_status: string | null;
  desensitization_counts: Record<string, number> | null;
  desensitization_message: string | null;
  suggested_asset_type: string | null;
  suggested_version?: string | null;
  version_source?: "source_filename" | "ai_content" | "default_needs_confirmation" | null;
  version_confidence?: "high" | "medium" | "low" | null;
  version_reason?: string | null;
  suggested_confidentiality_level: string | null;
  confidentiality_source?: "ai_content" | "default_needs_confirmation" | null;
  confidentiality_confidence?: "high" | "medium" | "low" | null;
  confidentiality_reason?: string | null;
  suggested_ai_access_level: string | null;
  suggested_phase_key: string | null;
  confidence: number | null;
  suggestion_generation_status: "generated" | "needs_correction" | "needs_manual_completion";
  suggestion_generation_reason: string;
  // 生成失败原因类别（response_error / timeout 可自动重试；其余为永久性失败）。
  generation_error_category?: string | null;
  naming_compliant: boolean | null;
  naming_parsed_fields: NamingFields | null;
  naming_anomalies: unknown[] | null;
  // 抽取与去重。extracted_text_preview 仅完整视图返回。
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
  confidentiality_level: string;
  // PBC-38：可选模型选择（对底座 id 不可逆的 model_ref，绝不发送真实 model_id）。
  // 缺省走平台默认；仅在首建该 scope 的 KB 时生效，已有 KB 沿用其锁定模型。
  embedding_model_ref?: string;
  rerank_model_ref?: string;
  acknowledged_naming_warning_codes?: string[];
  naming?: import("./naming").NamingConfirmationDTO;
}

export interface IngestConfirmResponseDTO {
  task_id: string;
  status: string;
  result_asset_id: string | null;
  review_id?: string | null;
  // WeKnora 解析安全业务状态（processing/completed/failed/duplicate）；未启用底座时 null。
  parse_status?: string | null;
  // 平台级索引状态：indexed | index_failed | skipped。
  // index_failed = 资产已确认落库但底座索引失败、可重试；前端据此提示而非表现为完全成功。
  index_status?: string | null;
  canonical_name?: string | null;
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
  suggestion_generation_status: "generated" | "needs_correction" | "needs_manual_completion";
  suggestion_generation_reason: string;
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

// 业务侧待确认任务。仅安全元数据；
// 无 source_file_ref / storage_ref / WeCom file_id / 下载 URL / token / WeKnora id。
export interface PendingIngestItemDTO {
  id: string;
  source: string;
  status: string;
  source_file_name: string;
  target_scope: string | null;
  target_project_id: string | null;
  // 文件形成日期建议（YYYY-MM-DD；客户端文件修改时间 / 文件名兜底），人工可改可清空。
  suggested_formed_on?: string | null;
  can_batch_confirm: boolean;
  can_batch_reject: boolean;
  extraction_status: string | null;
  error_type: string | null;
  error_message: string | null;
  suggested_title: string | null;
  suggested_one_liner: string | null;
  suggested_version?: string | null;
  version_source?: "source_filename" | "ai_content" | "default_needs_confirmation" | null;
  version_confidence?: "high" | "medium" | "low" | null;
  version_reason?: string | null;
  suggested_confidentiality_level?: string | null;
  confidentiality_source?: "ai_content" | "default_needs_confirmation" | null;
  confidentiality_confidence?: "high" | "medium" | "low" | null;
  confidentiality_reason?: string | null;
  naming_parsed_fields: NamingFields | null;
  confidence: number | null;
  suggestion_generation_status: "generated" | "needs_correction" | "needs_manual_completion";
  suggestion_generation_reason: string;
  result_asset_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface PendingIngestListResponseDTO {
  items: PendingIngestItemDTO[];
  total: number;
}
