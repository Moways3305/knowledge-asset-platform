import { apiGet, apiPost } from "./http";

export interface KnowledgeTask {
  id: string;
  instruction: string;
  created_at: string;
  status: "queued" | "searching" | "checking" | "ready" | "empty" | "failed";
}
export interface KnowledgeEvidence {
  asset_id: string;
  version_id: string;
  title: string;
  version: string;
  summary: string | null;
  original: boolean;
  matched: string[];
  summary_matched: string[];
  unmatched: string[];
  old_source_links: { asset_id: string; title: string }[];
  needs_update: boolean;
  pending_update: boolean;
  history_truncated: boolean;
  parsed: boolean;
  correction_status: string | null;
  compared_version: string | null;
  changed_fields: string[];
  previous_summary: string | null;
  current_summary: string | null;
  updated_at: string;
}
export interface KnowledgeTaskDetail extends KnowledgeTask {
  failure_reason: "access_changed" | "tool_error" | null;
  mode: string | null;
  candidates: number;
  inspected: number;
  evidence: KnowledgeEvidence | null;
  availability: "available" | "changed" | "unavailable" | null;
}
const path = (key: string) =>
  `/api/v1/maintenance-agent/libraries/${encodeURIComponent(key)}/tasks` as const;
export const delegate = (key: string, instruction: string, request_id: string) =>
  apiPost<KnowledgeTask>(path(key), { instruction, request_id });
export const recentTasks = (key: string, signal: AbortSignal) =>
  apiGet<KnowledgeTask[]>(path(key), signal);
export const fetchTask = (key: string, id: string, signal: AbortSignal) =>
  apiGet<KnowledgeTaskDetail>(`${path(key)}/${id}`, signal);
