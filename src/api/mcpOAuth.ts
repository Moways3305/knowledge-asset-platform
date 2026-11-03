import { apiDelete, apiGet, apiPost } from "./http";

export interface McpOAuthGrant {
  id: string;
  name: string;
  operations_enabled: boolean;
  expires_at: string;
}

export interface McpConsentView {
  client_name: string;
  redirect_origin: string;
  operations_requested: boolean;
}

export function fetchMcpOAuthGrants() {
  return apiGet<{ items: McpOAuthGrant[] }>("/api/v1/auth/mcp-oauth/grants");
}

export function revokeMcpOAuthGrant(id: string) {
  return apiDelete<void>(`/api/v1/auth/mcp-oauth/grants/${encodeURIComponent(id)}`);
}

export function fetchMcpConsent(requestId: string) {
  return apiGet<McpConsentView>(`/api/v1/auth/mcp-oauth/requests/${encodeURIComponent(requestId)}`);
}

export function decideMcpConsent(
  requestId: string,
  decision: { approved: boolean; operations: boolean },
) {
  return apiPost<{ redirect_url: string }>(
    `/api/v1/auth/mcp-oauth/requests/${encodeURIComponent(requestId)}`,
    decision,
  );
}
