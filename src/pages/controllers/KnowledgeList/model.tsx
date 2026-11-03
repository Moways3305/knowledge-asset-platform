import type { AssetStatus, ConfidentialityLevel, KnowledgePageVM } from "../../../types/knowledge";
export const PAGE_SIZE = 20;

export const ASSET_STATUSES: AssetStatus[] = ["active", "needs_update", "deprecated", "archived"];

export const CONFIDENTIALITY_LEVELS: ConfidentialityLevel[] = ["L1", "L2", "L3", "L4", "L5"];

export const confidentialityLabels: Record<ConfidentialityLevel, string> = {
  L1: "L1 · 公开",
  L2: "L2 · 内部",
  L3: "L3 · 受限",
  L4: "L4 · 机密",
  L5: "L5 · 高度机密",
};

export const statusTones: Record<AssetStatus, "success" | "warning" | "neutral"> = {
  active: "success",
  needs_update: "warning",
  deprecated: "neutral",
  archived: "neutral",
};

export const emptyPage = (): KnowledgePageVM => ({
  items: [],
  total: 0,
  page: 1,
  pageSize: PAGE_SIZE,
  hasNext: false,
});
