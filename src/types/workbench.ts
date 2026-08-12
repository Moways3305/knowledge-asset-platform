export type WorkbenchSectionStatus = "available" | "empty" | "forbidden" | "error";

export interface WorkbenchTodoItemDTO {
  key: string;
  count: number;
  severity: string;
  route_key: string;
  action_key: string;
}

export interface WorkbenchTodosSectionDTO {
  status: WorkbenchSectionStatus;
  error_code: string | null;
  items: WorkbenchTodoItemDTO[];
  total: number;
}

export type WorkbenchTaskStatus =
  | "needs_action"
  | "submitted"
  | "processing"
  | "completed"
  | "partial"
  | "failed";
export type WorkbenchTaskPriority = "urgent" | "high" | "normal" | "low";

export interface WorkbenchTaskItemDTO {
  task_ref: string;
  task_type: string;
  object_name: string;
  project_name: string | null;
  status: WorkbenchTaskStatus;
  priority: WorkbenchTaskPriority;
  assignee: string;
  responsibility: string;
  created_at: string | null;
  updated_at: string | null;
  waiting_minutes: number | null;
  next_action_key: string | null;
  next_action_label: string;
  route_key: string | null;
  result_summary: string | null;
  progress_total: number | null;
  progress_success: number | null;
  progress_failed: number | null;
}

export interface WorkbenchTaskCenterSectionDTO {
  status: WorkbenchSectionStatus;
  error_code: string | null;
  summary: {
    needs_action: number;
    running: number;
    attention: number;
    completed_today: number;
  };
  priority_items: WorkbenchTaskItemDTO[];
  my_tasks: WorkbenchTaskItemDTO[];
  running_jobs: WorkbenchTaskItemDTO[];
  attention_items: WorkbenchTaskItemDTO[];
  recent_completed: WorkbenchTaskItemDTO[];
}

export interface WorkbenchOperationCardDTO {
  key: string;
  label: string;
  count: number;
  severity: string;
  action_hint: string | null;
  scope?: string | null;
  project_id?: string | null;
  context_label?: string | null;
}

export interface WorkbenchOperationsDataDTO {
  title_visible: boolean;
  scope: string;
  window_days: number;
  cards: WorkbenchOperationCardDTO[];
  indexing: {
    index_failed: number;
    skipped: number;
    not_indexed: number;
    parse_failed: number;
    parse_pending: number;
    parse_processing: number;
    kb_init_failed: number;
  };
  access: {
    pending_original_requests: number;
    overdue_original_requests: number;
    recent_auto_approved: number;
    timeout_enabled: boolean;
  };
  lifecycle: {
    archive_candidates: number;
    archive_warnings: number;
    needs_update: number;
    reuse_upgrade_candidates: number;
  };
}

export interface WorkbenchOperationsSectionDTO {
  status: WorkbenchSectionStatus;
  error_code: string | null;
  data: WorkbenchOperationsDataDTO | null;
}

export interface WorkbenchProjectItemDTO {
  project_id: string;
  name: string;
  status: string;
  project_role: string;
  lifecycle_route_key: string | null;
  lifecycle_phase_key: string | null;
}

export interface WorkbenchProjectsSectionDTO {
  status: WorkbenchSectionStatus;
  error_code: string | null;
  items: WorkbenchProjectItemDTO[];
  total: number;
}

export interface WorkbenchRecentActivityItemDTO {
  asset_id: string;
  title: string;
  scope: string;
  zone: string;
  asset_type: string;
  confidentiality_level: string;
  summary: string | null;
  project_name: string | null;
  updated_at: string | null;
}

export interface WorkbenchRecentActivitySectionDTO {
  status: WorkbenchSectionStatus;
  error_code: string | null;
  items: WorkbenchRecentActivityItemDTO[];
  total: number;
}

export interface WorkbenchOverviewDTO {
  task_center: WorkbenchTaskCenterSectionDTO;
  todos: WorkbenchTodosSectionDTO;
  operations: WorkbenchOperationsSectionDTO;
  projects: WorkbenchProjectsSectionDTO;
  recent_activity: WorkbenchRecentActivitySectionDTO;
}
