// 自助 WorkBuddy 接入：当前用户生成 / 重置 / 撤销自己的 WorkBuddy MCP 配置。
// token 明文仅在生成 / 重置响应里出现一次，前端不持久化（不写 localStorage/sessionStorage）。
import { apiDelete, apiGet, apiPost, BASE_URL } from "./http";

export type WorkbuddyPlatform = "windows" | "macos";
export type WorkbuddyArchitecture = "x64" | "arm64";

// ---- 绑定状态（无 token / token_hash） ----
export interface WorkbuddyTokenStatusVM {
  enabled: boolean;
  boundUserName: string | null;
  lastRotatedAt: string | null;
  lastConnectedAt: string | null;
}

interface WorkbuddyTokenStatusDTO {
  enabled: boolean;
  provider: string;
  bound_user_name: string | null;
  last_rotated_at: string | null;
  last_connected_at: string | null;
}

// ---- 生成 / 重置结果（一次性 token + 可复制 mcp.json） ----
export interface WorkbuddyConfigVM {
  platform: WorkbuddyPlatform;
  mcpConfigJson: string;
}

interface WorkbuddyConfigDTO {
  token: string;
  mcp_config: Record<string, unknown>;
  platform: WorkbuddyPlatform;
}

export interface WorkbuddyConnectorArtifactVM {
  platform: WorkbuddyPlatform;
  architecture: WorkbuddyArchitecture;
  version: string;
  filename: string;
  sha256: string;
  downloadUrl: string;
  releaseStatus: "production" | "internal";
  signed: boolean;
  notarized: boolean;
}

interface WorkbuddyConnectorArtifactDTO {
  platform: WorkbuddyPlatform;
  architecture: WorkbuddyArchitecture;
  version: string;
  filename: string;
  sha256: string;
  download_path: string;
  release_status: "production" | "internal";
  signed: boolean;
  notarized: boolean;
}

interface WorkbuddyConnectorManifestDTO {
  version: string;
  artifacts: WorkbuddyConnectorArtifactDTO[];
}

export interface WorkbuddyConnectorManifestVM {
  version: string;
  artifacts: WorkbuddyConnectorArtifactVM[];
}

export async function fetchWorkbuddyToken(): Promise<WorkbuddyTokenStatusVM> {
  const d = await apiGet<WorkbuddyTokenStatusDTO>(`/api/v1/auth/workbuddy-token`);
  return {
    enabled: d.enabled,
    boundUserName: d.bound_user_name,
    lastRotatedAt: d.last_rotated_at,
    lastConnectedAt: d.last_connected_at,
  };
}

export async function fetchWorkbuddyConnectors(): Promise<WorkbuddyConnectorManifestVM> {
  const data = await apiGet<WorkbuddyConnectorManifestDTO>(`/api/v1/auth/workbuddy-connectors`);
  return {
    version: data.version,
    artifacts: data.artifacts.map((item) => ({
      platform: item.platform,
      architecture: item.architecture,
      version: item.version,
      filename: item.filename,
      sha256: item.sha256,
      downloadUrl: `${BASE_URL}${item.download_path}`,
      releaseStatus: item.release_status,
      signed: item.signed,
      notarized: item.notarized,
    })),
  };
}

export async function regenerateWorkbuddyToken(
  platform: WorkbuddyPlatform,
): Promise<WorkbuddyConfigVM> {
  const data = await apiPost<WorkbuddyConfigDTO>(`/api/v1/auth/workbuddy-token/regenerate`, {
    platform,
  });
  return {
    platform: data.platform,
    mcpConfigJson: JSON.stringify(data.mcp_config, null, 2),
  };
}

export async function revokeWorkbuddyToken(): Promise<void> {
  await apiDelete<WorkbuddyTokenStatusDTO>(`/api/v1/auth/workbuddy-token`);
}
