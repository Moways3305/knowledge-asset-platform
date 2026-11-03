import { BookOpenCheck, BriefcaseBusiness, Files, LayoutTemplate, Lightbulb } from "lucide-react";
import { ApiError } from "../../../api/http";
import type {
  PersonalKnowledgeItemVM,
  PersonalKnowledgeState,
  PersonalKnowledgeSummaryDTO,
} from "../../../types/myKnowledge";
export const PAGE_SIZE = 20;

export const SAFE_FALLBACK = "信息待确认";

export const emptySummary: PersonalKnowledgeSummaryDTO = {
  total_assets: 0,
  awaiting_confirmation: 0,
  pending_project_review: 0,
  active_in_project: 0,
  created_this_month: 0,
};

export const typeConfig = {
  methodology: { label: "方法论", icon: BookOpenCheck, tone: "blue" },
  deliverable: { label: "交付物", icon: BriefcaseBusiness, tone: "gold" },
  case: { label: "案例", icon: Files, tone: "green" },
  template: { label: "模板", icon: LayoutTemplate, tone: "violet" },
  insight: { label: "洞察", icon: Lightbulb, tone: "amber" },
} as const;

export const stateConfig: Record<PersonalKnowledgeState, { label: string; tone: string }> = {
  awaiting_confirmation: { label: "待本人确认", tone: "warning" },
  ready_to_submit: { label: "可提交项目", tone: "ready" },
  pending_project_review: { label: "待项目经理审批", tone: "pending" },
  active_in_project: { label: "已进入项目", tone: "success" },
  project_rejected: { label: "项目未通过", tone: "danger" },
};

export const evidenceCategoryLabels: Record<string, string> = {
  meeting_minutes: "会议纪要",
  wecom_record: "企微记录",
  client_email: "客户邮件",
  acceptance_doc: "验收单",
  delivery_adoption: "交付采纳",
};

export const evidenceCategories = Object.keys(evidenceCategoryLabels);

export type DialogKind =
  | "create-kb"
  | "rename-kb"
  | "confirm"
  | "submit"
  | "evidence"
  | "edit"
  | "delete"
  | "bulk-delete"
  | null;

export type LoadState = "loading" | "ready" | "error" | "forbidden";

export type EvidenceType = "internal_sharing" | "client_validation";

export function kbStatus(status?: string | null) {
  if (status === "active") return { label: "运行正常", tone: "success" };
  if (status === "init_failed") return { label: "初始化失败", tone: "danger" };
  return { label: SAFE_FALLBACK, tone: "neutral" };
}

export function safeActionError(error: unknown, fallback: string) {
  if (error instanceof ApiError && error.status === 403) return "当前身份无权执行此操作";
  if (
    error instanceof ApiError &&
    error.status === 409 &&
    error.deniedReason === "personal_asset_project_locked"
  ) {
    return "项目审核或项目使用中的资料不可直接修改";
  }
  return fallback;
}

export function isProjectLocked(item: PersonalKnowledgeItemVM) {
  return ["pending_project_review", "active_in_project"].includes(item.personalState);
}
