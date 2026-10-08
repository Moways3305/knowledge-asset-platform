import { apiGet, apiPatch, apiPost, ApiError } from "./http";

export interface Correction {
  id: string;
  status: "open" | "resolved" | "verified";
  description: string;
  resolution: string | null;
  updated_at: string;
  can_resolve: boolean;
  can_verify: boolean;
}

export interface TrustState {
  asset_id: string;
  updated_at: string;
  maintainer_user_id: string | null;
  maintainer_name: string | null;
  review_due_at: string | null;
  verified_at: string | null;
  freshness: "unreviewed" | "verified" | "changed" | "due" | "needs_update" | "archived";
  replacement_asset_id: string | null;
  can_manage: boolean;
  corrections: Correction[];
  maintainers: { id: string; name: string }[];
}

const path = (id: string) => `/api/v1/knowledge/${encodeURIComponent(id)}/trust`;
export async function fetchTrust(id: string): Promise<TrustState> {
  const state = await apiGet<TrustState>(path(id));
  if (
    !state ||
    typeof state.asset_id !== "string" ||
    !Array.isArray(state.corrections) ||
    !Array.isArray(state.maintainers) ||
    typeof state.updated_at !== "string"
  ) {
    throw new ApiError(502, "复核信息格式不正确，请重试或联系管理员。");
  }
  return state;
}
export interface MaintenancePage {
  items: {
    asset_id: string;
    title: string;
    scope: string;
    freshness: TrustState["freshness"];
    review_due_at: string | null;
    needs_correction: boolean;
    awaiting_my_verification: boolean;
  }[];
  total: number;
  page: number;
  page_size: number;
}
export const fetchMaintenance = (page: number) =>
  apiGet<MaintenancePage>(`/api/v1/knowledge-maintenance?page=${page}`);
export const saveTrustPolicy = (id: string, body: Record<string, unknown>) =>
  apiPatch<TrustState>(`${path(id)}/policy`, body);
export const fetchReplacementOptions = (id: string, keyword: string) =>
  apiGet<{ asset_id: string; title: string }[]>(
    `${path(id)}/replacements?keyword=${encodeURIComponent(keyword)}`,
  );
export const reviewTrust = (id: string, body: Record<string, unknown>) =>
  apiPost<TrustState>(`${path(id)}/review`, body);
export const replaceTrust = (id: string, body: Record<string, unknown>) =>
  apiPost<TrustState>(`${path(id)}/replacement`, body);
export const reportCorrection = (id: string, body: Record<string, unknown>) =>
  apiPost<TrustState>(`${path(id)}/corrections`, body);
export const transitionCorrection = (id: string, ticket: string, body: Record<string, unknown>) =>
  apiPost<TrustState>(`${path(id)}/corrections/${encodeURIComponent(ticket)}`, body);
