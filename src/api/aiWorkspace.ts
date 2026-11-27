import { apiDelete, apiGet, apiPatch, apiPost } from "./http";

export interface WorkspaceSession {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}
export interface WorkspaceRun {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "stopped";
  model_ref: string;
  context_key: string | null;
  error_code: string | null;
  created_at: string;
  finished_at: string | null;
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
  tools: { key: string; label: string; description: string }[];
}
const base = "/api/v1/ai-workspace" as const;
const sessionPath = (id: string) => `${base}/sessions/${encodeURIComponent(id)}` as const;
export const getWorkspaceOptions = (signal?: AbortSignal) =>
  apiGet<WorkspaceOptions>(`${base}/options`, signal);
export const listWorkspaceSessions = (signal?: AbortSignal) =>
  apiGet<WorkspaceSession[]>(`${base}/sessions`, signal);
export const createWorkspaceSession = (request_id: string) =>
  apiPost<WorkspaceSession>(`${base}/sessions`, { request_id });
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
export const retryWorkspaceRun = (id: string, runId: string, request_id: string) =>
  apiPost<WorkspaceRun>(`${sessionPath(id)}/runs/${encodeURIComponent(runId)}/retry`, {
    request_id,
  });
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
  return run.status === "queued" || run.status === "running";
}
