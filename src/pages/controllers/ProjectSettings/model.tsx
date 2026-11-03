import { ApiError } from "../../../api/http";
import type { ProjectSettingsDTO } from "../../../types/projectSettings";
export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const ROUTE_OPTIONS = ["route_A", "route_B", "route_C"];

export const PROJECT_ROLE_OPTIONS = ["coach", "consultant"];

export const PENDING_REVIEW_STATUSES = new Set(["pending_reviewer", "approval_failed"]);

export const routeLabel: Record<string, string> = {
  route_A: "完整路线",
  route_B: "年度辅导循环",
  route_C: "专项诊断",
};

export const projectRoleLabel: Record<string, string> = {
  project_manager: "项目经理",
  coach: "辅导老师",
  consultant: "顾问",
};

export const projectStatusLabel: Record<string, string> = {
  active: "进行中",
  completed: "已完成",
  archived: "已归档",
  inactive: "已停用",
};

export const memberStatusLabel: Record<string, string> = {
  active: "有效",
  inactive: "已停用",
};

export const reviewTypeLabel: Record<string, string> = {
  material_to_asset: "资料资产化",
  personal_to_project: "个人知识升级",
  project_ingest_approval: "项目知识入库",
  lifecycle_change: "生命周期变更",
};

export type SettingsDraft = {
  lifecycleRouteKey: string;
  lifecyclePhaseKey: string;
  forceReviewOnIngest: boolean;
  wecomGroupId: string | null;
  projectCode: string;
  projectCodeActive: boolean;
  namingDefaultConfidentiality: string;
};

export const draftFromSettings = (settings: ProjectSettingsDTO): SettingsDraft => ({
  lifecycleRouteKey: settings.lifecycle_route_key ?? "",
  lifecyclePhaseKey: settings.lifecycle_phase_key ?? "",
  forceReviewOnIngest: settings.force_review_on_ingest,
  wecomGroupId: null,
  projectCode: settings.project_code ?? "",
  projectCodeActive: settings.project_code_active ?? false,
  namingDefaultConfidentiality: settings.naming_default_confidentiality ?? "L2",
});

export const safeError = (error: unknown, fallback: string): string => {
  if (error instanceof ApiError && error.status === 403) {
    return error.deniedReason === "project_membership_required"
      ? "当前身份不是该项目成员"
      : "当前身份无权执行此操作";
  }
  if (error instanceof ApiError && error.status === 409) {
    return "项目状态已变化，请刷新后重试";
  }
  return fallback;
};
