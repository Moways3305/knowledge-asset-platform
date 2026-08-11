import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  CheckCircle2,
  Circle,
  CircleDashed,
  Clock3,
  LoaderCircle,
  ShieldAlert,
  XCircle,
} from "lucide-react";

export type OperationStatus =
  | "not_started"
  | "queued"
  | "processing"
  | "awaiting_confirmation"
  | "completed"
  | "partial"
  | "failed"
  | "attention";

export interface OperationStatusDefinition {
  label: string;
  guidance: string;
  tone: "neutral" | "info" | "success" | "warning" | "danger";
  Icon: LucideIcon;
}

export const OPERATION_STATUS: Record<OperationStatus, OperationStatusDefinition> = {
  not_started: {
    label: "未开始",
    guidance: "检查所需信息后开始操作。",
    tone: "neutral",
    Icon: Circle,
  },
  queued: {
    label: "已排队",
    guidance: "请求已提交，正在等待执行。",
    tone: "info",
    Icon: Clock3,
  },
  processing: {
    label: "处理中",
    guidance: "任务仍在执行，请等待最终结果。",
    tone: "info",
    Icon: LoaderCircle,
  },
  awaiting_confirmation: {
    label: "待确认",
    guidance: "核对当前信息并决定下一步。",
    tone: "warning",
    Icon: CircleDashed,
  },
  completed: {
    label: "已完成",
    guidance: "任务已达到最终完成状态。",
    tone: "success",
    Icon: CheckCircle2,
  },
  partial: {
    label: "部分完成",
    guidance: "保留成功结果，并处理剩余项目。",
    tone: "warning",
    Icon: AlertTriangle,
  },
  failed: {
    label: "失败",
    guidance: "查看安全摘要，修正后重试。",
    tone: "danger",
    Icon: XCircle,
  },
  attention: {
    label: "需注意",
    guidance: "当前状态需要人工检查。",
    tone: "warning",
    Icon: ShieldAlert,
  },
};

export function operationStatusFromJob(status: string): OperationStatus {
  if (status === "queued") return "queued";
  if (status === "running" || status === "processing") return "processing";
  if (status === "completed") return "completed";
  if (status === "completed_with_errors") return "partial";
  if (status === "failed") return "failed";
  if (status === "no_action") return "attention";
  return "attention";
}
