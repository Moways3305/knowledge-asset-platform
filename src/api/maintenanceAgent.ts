import { apiDelete, apiGet, apiPost, apiPut } from "./http";

export interface ScanSettings {
  model_ref: string;
  daily_hour: number;
  weekly_day: number;
  digest_hour: number;
  overdue_days: number;
  required_tags: string[];
  required_sections: string[];
  similarity_threshold: number;
  max_body_chars: number;
}
export interface AgentModelOption {
  model_ref: string;
  display_name: string;
  provider: string;
  model_name: string;
  enabled: boolean;
  is_default: boolean;
}
export interface AgentModelOptions {
  items: AgentModelOption[];
  default_missing: boolean;
}
export const fetchAgentModels = () => apiGet<AgentModelOptions>("/api/v1/generation/model-options");
export interface AgentPolicy {
  id: string | null;
  library_key: string;
  name: string;
  enabled: boolean;
  content_authorized: boolean;
  revision: number;
  settings: ScanSettings;
  last_error: string | null;
  can_configure: boolean;
}
export interface MaintenanceIssue {
  id: string;
  asset_id: string;
  title: string;
  library_key: string;
  rule: string;
  category: string;
  status: string;
  suspected: boolean;
  priority?: "actionable" | "suggestion";
  first_seen_at: string;
  last_seen_at: string;
  updated_at: string;
  snooze_until: string | null;
  responsible: { id: string; name: string }[];
  can_act: boolean;
}
export interface IssueDetail extends MaintenanceIssue {
  evidence: {
    quote?: string;
    offset?: number;
    related_asset_id?: string;
    related_title?: string;
    basis?: string;
    similarity?: number;
    due_at?: string;
    missing_tags?: string[];
    missing_sections?: string[];
  };
  evidence_available: boolean;
  current_version_matches: boolean;
  history: { action: string; reason: string; created_at: string }[];
}
export interface ScanRun {
  id: string;
  policy_id: string;
  kind: string;
  status: string;
  target_count: number;
  completed_count: number;
  incomplete_count: number;
  skipped_count: number;
  reasons: Record<string, number>;
  started_at: string;
  finished_at: string | null;
  last_progress_at?: string;
  can_retry?: boolean;
}
export interface ScanScope {
  assessed_at: string;
  visible_count: number;
  target_count: number;
  excluded_counts: Record<string, number>;
}
export interface ScanRunDetail extends ScanRun {
  library_key: string;
  historical_details_available: boolean;
  scope_snapshot: ScanScope | null;
  current_scope: ScanScope;
  content_authorized: boolean | null;
  settings: ScanSettings | null;
  items: {
    asset_id: string;
    title: string;
    status: string;
    version_id: string | null;
    current_version_matches: boolean;
    coverage: Record<string, string>;
    findings: Record<string, number>;
    reasons: string[];
    checked_at: string | null;
    progress?: Record<string, number>;
  }[];
  total: number;
  page: number;
  page_size: number;
}
export const fetchAgentRun = (key: string, id: string, page = 1, status = "") =>
  apiGet<ScanRunDetail>(
    `/api/v1/maintenance-agent/policies/${encodeURIComponent(key)}/runs/${encodeURIComponent(id)}?page=${page}${status ? `&status=${status}` : ""}`,
  );
export interface IssuePage {
  counts?: Record<string, number>;
  items: MaintenanceIssue[];
  total: number;
  page: number;
  page_size: number;
}
export interface IssueAction {
  action: "in_progress" | "recheck" | "resolved" | "false_positive" | "snoozed";
  expected_updated_at: string;
  reason: string;
  snooze_until?: string;
}

export const fetchAgentPolicies = () => apiGet<AgentPolicy[]>("/api/v1/maintenance-agent/policies");
export const saveAgentPolicy = (
  key: string,
  policy: Pick<AgentPolicy, "enabled" | "content_authorized" | "settings"> & {
    expected_revision: number;
  },
) => apiPut<AgentPolicy>(`/api/v1/maintenance-agent/policies/${encodeURIComponent(key)}`, policy);
export const startAgentRun = (key: string) =>
  apiPost<ScanRun>(`/api/v1/maintenance-agent/policies/${encodeURIComponent(key)}/runs`, {});
export const cancelAgentRun = (key: string, id: string) =>
  apiPost<ScanRun>(
    `/api/v1/maintenance-agent/policies/${encodeURIComponent(key)}/runs/${encodeURIComponent(id)}/cancel`,
    {},
  );
export const retryAgentRun = (key: string, id: string) =>
  apiPost<ScanRun>(
    `/api/v1/maintenance-agent/policies/${encodeURIComponent(key)}/runs/${encodeURIComponent(id)}/retry`,
    {},
  );
export const deleteAgentRun = (key: string, id: string) =>
  apiDelete<{ deleted_count: number }>(
    `/api/v1/maintenance-agent/policies/${encodeURIComponent(key)}/runs/${encodeURIComponent(id)}`,
  );
export const deleteAgentRuns = (key: string, ids: string[]) =>
  apiPost<{ deleted_count: number }>(
    `/api/v1/maintenance-agent/policies/${encodeURIComponent(key)}/runs/delete`,
    { run_ids: ids },
  );
export const fetchAgentRuns = (key: string, page = 1) =>
  apiGet<ScanRun[]>(
    `/api/v1/maintenance-agent/policies/${encodeURIComponent(key)}/runs?page=${page}`,
  );
export const fetchAgentIssues = (params: URLSearchParams) =>
  apiGet<IssuePage>(`/api/v1/maintenance-agent/issues?${params}`);
export const fetchAgentIssue = (id: string) =>
  apiGet<IssueDetail>(`/api/v1/maintenance-agent/issues/${id}`);
export const actOnAgentIssue = (id: string, action: IssueAction) =>
  apiPost<IssueDetail>(`/api/v1/maintenance-agent/issues/${id}/actions`, action);
