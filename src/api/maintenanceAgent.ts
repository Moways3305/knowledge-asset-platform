import { apiGet, apiPost, apiPut } from "./http";

export interface ScanSettings {
  daily_hour: number;
  weekly_day: number;
  digest_hour: number;
  overdue_days: number;
  required_tags: string[];
  required_sections: string[];
  similarity_threshold: number;
  max_body_chars: number;
}
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
}
export interface IssuePage {
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
