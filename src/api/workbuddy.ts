// 自助 WorkBuddy 接入：当前用户生成 / 重置 / 撤销自己的 WorkBuddy MCP 配置。
// token 明文仅在生成 / 重置响应里出现一次，前端不持久化（不写 localStorage/sessionStorage）。
import { apiGet, apiPostNoBody, apiDelete } from "./http";

// ---- 绑定状态（无 token / token_hash） ----
export interface WorkbuddyTokenStatusVM {
  enabled: boolean;
  boundUserName: string | null;
  lastRotatedAt: string | null;
}

interface WorkbuddyTokenStatusDTO {
  enabled: boolean;
  provider: string;
  bound_user_id: string | null;
  bound_user_name: string | null;
  created_at: string | null;
  updated_at: string | null;
  last_rotated_at: string | null;
}

// ---- 生成 / 重置结果（一次性 token + 可复制 mcp.json） ----
export interface WorkbuddyConfigVM {
  token: string;
  mcpConfigJson: string;
}

interface WorkbuddyConfigDTO {
  token: string;
  mcp_config: Record<string, unknown>;
}

export async function fetchWorkbuddyToken(): Promise<WorkbuddyTokenStatusVM> {
  const d = await apiGet<WorkbuddyTokenStatusDTO>(`/api/v1/auth/workbuddy-token`);
  return { enabled: d.enabled, boundUserName: d.bound_user_name, lastRotatedAt: d.last_rotated_at };
}

export async function regenerateWorkbuddyToken(): Promise<WorkbuddyConfigVM> {
  const d = await apiPostNoBody<WorkbuddyConfigDTO>(`/api/v1/auth/workbuddy-token/regenerate`);
  return { token: d.token, mcpConfigJson: JSON.stringify(d.mcp_config, null, 2) };
}

export async function revokeWorkbuddyToken(): Promise<void> {
  await apiDelete<WorkbuddyTokenStatusDTO>(`/api/v1/auth/workbuddy-token`);
}
