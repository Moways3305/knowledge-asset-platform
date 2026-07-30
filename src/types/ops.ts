// 运维面板 DTO。仅安全运维元数据：绝不含 WeKnora kb/doc id / 模型 id /
// storage 引用 / source file 引用 / 下载 URL / token / 原文。

export interface OpsIndexingCountsDTO {
  index_failed: number;
  indexing: number;
  not_indexed: number;
  skipped: number;
  parse_pending: number;
  parse_processing: number;
  parse_failed: number;
  kb_init_failed: number;
}

export interface OpsIndexingFailedItemDTO {
  retry_target: string | null;
  title: string; // 纯 admin 看「（业务资产标题已隐藏）」；业务治理角色看真实标题
  scope: string;
  project_name: string | null;
  owner_name: string | null;
  index_status: string;
  index_error_code: string | null;
  index_error_message: string | null; // 用户态文案
  // 运营态诊断（含配置项名，绝不含值/内部 id/secret）。
  operator_error_message: string | null;
  remediation_hint: string | null;
  severity: string | null;
  diagnostic_category:
    | "configuration"
    | "external_service"
    | "source_content"
    | "permission"
    | "platform"
    | "unknown";
  diagnostic_label: string;
  retry_eligible: boolean;
  updated_at: string | null;
}

export interface OpsIndexingDTO {
  counts: OpsIndexingCountsDTO;
  reparse_actionable_count: number;
  recent_failed: OpsIndexingFailedItemDTO[];
  diagnostic_counts: Record<OpsIndexingFailedItemDTO["diagnostic_category"], number>;
  title_visible: boolean;
}

// 索引批量运维。请求只含安全筛选条件；响应只含安全统计 + 安全错误文案，
// 绝不含标题 / 原文 / 文件名 / WeKnora id / storage·source 引用 / token。
export interface IndexingRetryRequestDTO {
  scope?: "personal" | "project" | "company" | "all";
  project_id?: string | null;
  statuses?: string[]; // index_failed | skipped | not_indexed
  limit?: number;
}

export interface IndexingReparseRequestDTO {
  scope?: "personal" | "project" | "company" | "all";
  project_id?: string | null;
  parse_statuses?: string[]; // failed | pending | processing
  limit?: number;
}

export interface IndexingJobSummaryDTO {
  job_id: string;
  operation_type: string; // retry_index | reparse
  status: string; // queued | running | completed | completed_with_errors | failed | no_action
  scope_filter: Record<string, unknown> | null;
  requested_by_name: string | null;
  requested_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  total_count: number;
  success_count: number;
  failed_count: number;
  skipped_count: number;
  error_code: string | null;
  error_message: string | null;
  trace_id: string | null;
}

export interface IndexingJobListResponseDTO {
  items: IndexingJobSummaryDTO[];
  total: number;
}

export interface IndexingHealthTrendPointDTO extends OpsIndexingCountsDTO {
  observed_at: string;
  completed_jobs: number;
  failed_jobs: number;
  queued_jobs: number;
  oldest_queued_seconds: number | null;
}

export interface RuntimeHealthDTO {
  status: "healthy" | "stale" | "unknown";
  last_heartbeat_at: string | null;
  message: string;
}

export interface QueueHealthDTO {
  status: "healthy" | "degraded" | "unknown";
  queued_count: number;
  oldest_queued_seconds: number | null;
  message: string;
}

export interface IndexingHealthDTO {
  generated_at: string;
  window_hours: number;
  insufficient_data: boolean;
  message: string;
  queue: QueueHealthDTO;
  worker: RuntimeHealthDTO;
  beat: RuntimeHealthDTO;
  trend_points: IndexingHealthTrendPointDTO[];
}
