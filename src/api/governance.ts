import { apiGet, apiPost } from "./http";

export interface GovernanceItem {
  asset_id: string;
  title: string;
  asset_status: string;
  confidentiality_level: string;
  summary: string | null;
  updated_at: string;
  archived_at: string | null;
  archive_reason: string | null;
  signals: string[];
}
export interface GovernancePage {
  items: GovernanceItem[];
  total: number;
  page: number;
  page_size: number;
  counts: Record<string, number>;
}
export interface BatchResult {
  items: { asset_id: string; success: boolean; message: string }[];
}
export type ReasonCode = "historical" | "superseded" | "duplicate" | "low_value" | "other";
export function fetchGovernance(view: string, signal: string, keyword: string, page: number) {
  const qs = new URLSearchParams({ view, keyword, page: String(page) });
  if (signal) qs.set("signal", signal);
  return apiGet<GovernancePage>(`/api/v1/company-governance?${qs}`);
}
export function applyGovernance(
  items: GovernanceItem[],
  action: "archive" | "restore",
  reason_code: ReasonCode,
  reason: string,
  replacement?: string,
) {
  return apiPost<BatchResult>("/api/v1/company-governance/batch", {
    items: items.map((i) => ({
      asset_id: i.asset_id,
      expected_status: i.asset_status,
      expected_updated_at: i.updated_at,
    })),
    action,
    reason_code,
    reason,
    replacement_asset_id: replacement || null,
  });
}
