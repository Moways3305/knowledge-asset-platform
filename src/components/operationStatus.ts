import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  Circle,
  CircleDashed,
  Clock3,
  FileCheck2,
  LoaderCircle,
  RotateCcw,
  ShieldAlert,
  ShieldCheck,
  TimerOff,
  XCircle,
} from "lucide-react";

export type OperationStatus =
  | "not_started"
  | "queued"
  | "submitted"
  | "processing"
  | "awaiting_confirmation"
  | "awaiting_approval"
  | "attention"
  | "completed"
  | "partial"
  | "failed"
  | "cancelled"
  | "withdrawn"
  | "expired";

export interface OperationStatusDefinition {
  label: string;
  guidance: string;
  tone: "neutral" | "info" | "success" | "warning" | "danger";
  Icon: LucideIcon;
  terminal: boolean;
}

export const OPERATION_STATUS: Record<OperationStatus, OperationStatusDefinition> = {
  not_started: {
    label: "未开始",
    guidance: "检查所需信息后开始操作。",
    tone: "neutral",
    Icon: Circle,
    terminal: false,
  },
  queued: {
    label: "排队",
    guidance: "请求已进入队列，正在等待执行。",
    tone: "info",
    Icon: Clock3,
    terminal: false,
  },
  submitted: {
    label: "已提交",
    guidance: "系统已受理请求，但作业尚未完成。",
    tone: "info",
    Icon: FileCheck2,
    terminal: false,
  },
  processing: {
    label: "处理中",
    guidance: "任务仍在执行，请等待最终结果。",
    tone: "info",
    Icon: LoaderCircle,
    terminal: false,
  },
  awaiting_confirmation: {
    label: "待确认",
    guidance: "核对当前信息并决定下一步。",
    tone: "warning",
    Icon: CircleDashed,
    terminal: false,
  },
  awaiting_approval: {
    label: "待审批",
    guidance: "申请已提交，正在等待有权限的人员审批。",
    tone: "warning",
    Icon: ShieldCheck,
    terminal: false,
  },
  attention: {
    label: "需关注",
    guidance: "当前状态需要人工检查后再继续。",
    tone: "warning",
    Icon: ShieldAlert,
    terminal: false,
  },
  completed: {
    label: "已完成",
    guidance: "任务已达到最终完成状态。",
    tone: "success",
    Icon: CheckCircle2,
    terminal: true,
  },
  partial: {
    label: "部分完成",
    guidance: "保留成功结果，并处理剩余项目。",
    tone: "warning",
    Icon: AlertTriangle,
    terminal: true,
  },
  failed: {
    label: "失败，可重试",
    guidance: "查看安全摘要，修正后重试。",
    tone: "danger",
    Icon: XCircle,
    terminal: true,
  },
  cancelled: {
    label: "已取消",
    guidance: "任务已停止，不会继续执行。",
    tone: "neutral",
    Icon: Ban,
    terminal: true,
  },
  withdrawn: {
    label: "已撤销",
    guidance: "申请已由发起人撤回，不再等待处理。",
    tone: "neutral",
    Icon: RotateCcw,
    terminal: true,
  },
  expired: {
    label: "已过期",
    guidance: "任务已超过有效期，如仍需处理请重新发起。",
    tone: "neutral",
    Icon: TimerOff,
    terminal: true,
  },
};

export function operationStatusFromJob(status: string): OperationStatus {
  const normalized = status.trim().toLowerCase();
  if (["draft", "not_started"].includes(normalized)) return "not_started";
  if (["queued", "pending"].includes(normalized)) return "queued";
  if (["submitted", "accepted"].includes(normalized)) return "submitted";
  if (["running", "processing", "indexing", "migrating"].includes(normalized)) {
    return "processing";
  }
  if (["awaiting_confirmation", "pending_confirmation"].includes(normalized)) {
    return "awaiting_confirmation";
  }
  if (["awaiting_approval", "pending_approval"].includes(normalized)) return "awaiting_approval";
  if (["completed", "approved", "indexed"].includes(normalized)) return "completed";
  if (["completed_with_errors", "partial", "partially_completed"].includes(normalized)) {
    return "partial";
  }
  if (["failed", "error"].includes(normalized)) return "failed";
  if (["cancelled", "canceled"].includes(normalized)) return "cancelled";
  if (["withdrawn", "revoked"].includes(normalized)) return "withdrawn";
  if (normalized === "expired") return "expired";
  return "attention";
}

export function isTerminalOperationStatus(status: OperationStatus) {
  return OPERATION_STATUS[status].terminal;
}
