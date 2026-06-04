// Admin Audit API 的 DTO 类型（IMPLEMENT-09）。
// 字段按后端视图档位（admin_metadata / governance）选择性填充；
// 前端不展示 storage_ref / token / Dify 内部标识（后端本就不返回）。

export interface AuditEventDTO {
  id: string;
  log_type: string;
  action: string;
  actor_user_id: string | null;
  actor_name: string | null;
  actor_company_role: string | null;
  actor_project_role: string | null;
  target_type: string | null;
  target_id: string | null;
  severity: string | null;
  is_processed: boolean;
  processed_by: string | null;
  processed_at: string | null;
  trace_id: string;
  denied_reason: string | null;
  risk_level: string | null;
  created_at: string;
  before_snapshot: Record<string, unknown> | null;
  after_snapshot: Record<string, unknown> | null;
  extra: Record<string, unknown> | null;
}

export interface AuditListResponseDTO {
  items: AuditEventDTO[];
  total: number;
  page: number;
  page_size: number;
  view: string;
}

export interface AuditTraceResponseDTO {
  trace_id: string;
  items: AuditEventDTO[];
  view: string;
}

export interface MarkProcessedResponseDTO {
  event_id: string;
  is_processed: boolean;
  processed_by: string | null;
  processed_at: string | null;
}
