// Knowledge 运营洞察 DTO。仅安全聚合 + 安全提示：绝不含 WeKnora kb/doc id /
// storage·source 引用 / 下载 URL / token / cookie / api key / 文件名 / 原文。

export interface InsightCardDTO {
  key: string;
  label: string;
  count: number;
  severity: string; // info | warning | error
  action_hint: string | null;
}

export interface InsightJobItemDTO {
  job_id: string;
  operation_type: string;
  status: string;
  total_count: number;
  success_count: number;
  failed_count: number;
  skipped_count: number;
  requested_at: string | null;
  finished_at: string | null;
}

export interface IndexingInsightsDTO {
  index_failed: number;
  skipped: number;
  not_indexed: number;
  parse_failed: number;
  parse_pending: number;
  parse_processing: number;
  kb_init_failed: number;
  recent_jobs: InsightJobItemDTO[];
}

export interface AccessInsightsDTO {
  pending_original_requests: number;
  overdue_original_requests: number;
  recent_auto_approved: number;
  timeout_enabled: boolean;
}

export interface LifecycleInsightsDTO {
  archive_candidates: number;
  archive_warnings: number;
  needs_update: number;
  reuse_upgrade_candidates: number;
}

export interface RecommendationDTO {
  key: string;
  severity: string;
  message: string;
  target: string | null;
}

export interface InsightRecentItemDTO {
  asset_id: string;
  scope: string;
  status: string;
  title: string | null; // title_visible=false 时为 null（纯 admin）
  message: string | null;
  updated_at: string | null;
}

export interface KnowledgeOpsInsightsDTO {
  title_visible: boolean;
  scope: string;
  window_days: number;
  cards: InsightCardDTO[];
  indexing: IndexingInsightsDTO;
  access: AccessInsightsDTO;
  lifecycle: LifecycleInsightsDTO;
  recommendations: RecommendationDTO[];
  recent_items: InsightRecentItemDTO[];
}

