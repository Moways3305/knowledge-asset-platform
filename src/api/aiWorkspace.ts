import { apiDelete, apiGet, apiPatch, apiPost } from "./http";

export interface WorkspaceSession {
  id: string;
  title: string;
  agent_key?: string | null;
  created_at: string;
  updated_at: string;
}
export interface WorkspaceRun {
  id: string;
  status:
    | "queued"
    | "running"
    | "waiting"
    | "awaiting_confirmation"
    | "completed"
    | "failed"
    | "stopped";
  model_ref: string;
  context_key: string | null;
  error_code: string | null;
  created_at: string;
  finished_at: string | null;
  pending_action?: WorkspacePendingAction | null;
  waiting_reason?: string | null;
  step_count?: number;
  max_steps?: number;
}
export interface WorkspacePendingAction {
  id: string;
  tool: string;
  label: string;
  summary: string;
  arguments: Record<string, unknown>;
}
export interface WorkspaceAction {
  id: string;
  run_id: string;
  tool: string;
  label: string;
  status: "planned" | "awaiting_confirmation" | "approved" | "completed" | "rejected" | "waiting";
  summary: string;
  observation: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}
export interface WorkspaceMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  run_id: string;
  created_at: string;
}
export interface WorkspaceArtifact {
  id: string;
  title: string;
  content: string;
  revision: number;
  run_id: string;
  created_at: string;
  updated_at: string;
}
export interface WorkspaceDetail {
  session: WorkspaceSession;
  messages: WorkspaceMessage[];
  runs: WorkspaceRun[];
  artifacts: WorkspaceArtifact[];
  actions?: WorkspaceAction[];
}
export interface WorkspaceEvent {
  id: number;
  run_id: string | null;
  type: string;
  label: string;
  created_at: string;
}
export interface WorkspaceOptions {
  models: { model_ref: string; display_name: string; is_default: boolean }[];
  contexts: { key: string; label: string }[];
  tools: WorkspaceTool[];
  agents?: WorkspaceAgent[];
}
export interface WorkspaceAgent {
  key: string;
  label: string;
  description: string;
  tools: WorkspaceTool[];
}
export interface WorkspaceTool {
  key: string;
  label: string;
  description: string;
}
const base = "/api/v1/ai-workspace" as const;
const sessionPath = (id: string) => `${base}/sessions/${encodeURIComponent(id)}` as const;
export const getWorkspaceOptions = (signal?: AbortSignal) =>
  apiGet<WorkspaceOptions>(`${base}/options`, signal);
export const listWorkspaceSessions = (signal?: AbortSignal) =>
  apiGet<WorkspaceSession[]>(`${base}/sessions`, signal);
export const createWorkspaceSession = (request_id: string, agent_key: string | null = null) =>
  apiPost<WorkspaceSession>(`${base}/sessions`, { request_id, agent_key });
export const renameWorkspaceSession = (id: string, title: string) =>
  apiPatch<WorkspaceSession>(sessionPath(id), { title });
export const deleteWorkspaceSession = (id: string) => apiDelete<void>(sessionPath(id));
export const getWorkspaceDetail = (id: string, signal?: AbortSignal) =>
  apiGet<WorkspaceDetail>(sessionPath(id), signal);
export const getWorkspaceEvents = (id: string, after: number, signal?: AbortSignal) =>
  apiGet<{ events: WorkspaceEvent[]; cursor: number }>(
    `${sessionPath(id)}/events?after=${after}`,
    signal,
  );
export const sendWorkspaceMessage = (
  id: string,
  body: { request_id: string; content: string; model_ref: string; context_key: string | null },
) => apiPost<WorkspaceRun>(`${sessionPath(id)}/messages`, body);
export const stopWorkspaceRun = (id: string, runId: string) =>
  apiPost<WorkspaceRun>(`${sessionPath(id)}/runs/${encodeURIComponent(runId)}/stop`, {});
export const resumeWorkspaceRun = (
  id: string,
  runId: string,
  request_id: string,
  content?: string,
) =>
  apiPost<WorkspaceRun>(`${sessionPath(id)}/runs/${encodeURIComponent(runId)}/resume`, {
    request_id,
    content,
  });
export const decideWorkspaceAction = (
  id: string,
  runId: string,
  actionId: string,
  request_id: string,
  decision: "approve" | "reject",
) =>
  apiPost<WorkspaceRun>(
    `${sessionPath(id)}/runs/${encodeURIComponent(runId)}/actions/${encodeURIComponent(actionId)}`,
    { request_id, decision },
  );
export const saveWorkspaceArtifact = (
  id: string,
  artifactId: string,
  body: { title: string; content: string; expected_revision: number },
) =>
  apiPatch<WorkspaceArtifact>(
    `${sessionPath(id)}/artifacts/${encodeURIComponent(artifactId)}`,
    body,
  );

export function isWorkspaceRunActive(run: WorkspaceRun) {
  return ["queued", "running", "waiting", "awaiting_confirmation"].includes(run.status);
}
