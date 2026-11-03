import { ApiError } from "../../../api/http";
import type { ReviewItemDTO } from "../../../types/review";
export const SAFE_FALLBACK = "信息待确认";

export const confirmationLabel: Record<string, string> = {
  pending: "待确认",
  confirmed: "已确认",
  withdrawn: "已撤回",
  rejected: "已拒绝",
};

export function companyConfirmationLabel(status: string | null) {
  return status === null ? "待确认" : (confirmationLabel[status] ?? SAFE_FALLBACK);
}

export const reviewTypeLabel: Record<string, string> = {
  material_to_asset: "资料资产化",
  personal_to_project: "个人知识升级",
  project_to_company: "公司资产升级",
  lifecycle_change: "生命周期变更",
  project_ingest_approval: "项目知识入库",
};

export const statusLabel: Record<string, string> = {
  pending_evidence: "待补充证据",
  pending_reviewer: "待审核",
  approved: "已通过",
  rejected: "已拒绝",
  approving: "处理中",
  approval_failed: "处理失败",
};

export const statusTone: Record<string, string> = {
  pending_evidence: "is-pending",
  pending_reviewer: "is-pending",
  approved: "is-success",
  rejected: "is-danger",
  approving: "is-neutral",
  approval_failed: "is-danger",
};

export const statusFilters = [
  { token: "0", apiValue: "", label: "全部状态" },
  { token: "1", apiValue: "pending_evidence", label: "待补充证据" },
  { token: "2", apiValue: "pending_reviewer", label: "待审核" },
  { token: "3", apiValue: "approving", label: "处理中" },
  { token: "4", apiValue: "approval_failed", label: "处理失败" },
];

export const reviewTypeFilters = [
  { token: "0", apiValue: "", label: "全部类型" },
  { token: "1", apiValue: "project_ingest_approval", label: "项目知识入库" },
  { token: "2", apiValue: "material_to_asset", label: "资料资产化" },
  { token: "3", apiValue: "personal_to_project", label: "个人知识升级" },
  { token: "4", apiValue: "project_to_company", label: "公司资产升级" },
  { token: "5", apiValue: "lifecycle_change", label: "生命周期变更" },
];

export type Feedback = { tone: "success" | "error" | "info"; text: string } | null;

export function safeTitle(item: ReviewItemDTO) {
  return item.asset_title?.trim() || "待确认知识";
}

export function isForbidden(error: unknown) {
  return error instanceof ApiError && error.status === 403;
}
