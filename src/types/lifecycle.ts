// 知识生命周期动作 API 的 DTO 类型。
// 生命周期变更是治理流程；request 仅产生预警/候选，confirm 才人工确认状态变更。

export interface LifecycleActionResponseDTO {
  lifecycle_event_id: string;
  review_task_id: string | null;
  status: string;
  trace_id: string;
}

export interface ArchiveConfirmResponseDTO {
  asset_id: string;
  asset_status: string;
  archived_at: string | null;
  archive_reason: string | null;
  trace_id: string;
}

export interface ReenableConfirmResponseDTO {
  asset_id: string;
  asset_status: string;
  lifecycle_event_id: string;
  trace_id: string;
}

export interface LifecycleEventDTO {
  event_id: string;
  event_type: string;
  old_status: string | null;
  new_status: string | null;
  reason: string | null;
  actor_display: string | null;
  created_at: string;
  trace_id: string | null;
}

export interface LifecycleEventsResponseDTO {
  items: LifecycleEventDTO[];
}

